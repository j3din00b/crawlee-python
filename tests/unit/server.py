from __future__ import annotations

import asyncio
import base64
import gzip
import json
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from uvicorn.server import Server
from yarl import URL

from tests.unit.server_endpoints import (
    GENERIC_RESPONSE,
    HELLO_WORLD,
    INCAPSULA,
    ROBOTS_TXT,
    SECONDARY_INDEX,
    START_ENQUEUE,
)

if TYPE_CHECKING:
    from socket import socket

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Coroutine[None, None, None]]
PathHandler = Callable[[dict[str, Any], Receive, Send], Coroutine[None, None, None]]


def get_headers_dict(scope: dict[str, Any]) -> dict[str, str]:
    """Extract request headers and return them as a dictionary."""
    headers = {}
    for name, value in scope.get('headers', []):
        headers[name.decode()] = value.decode()
    return headers


def get_query_params(query_string: bytes) -> dict[str, str]:
    """Extract and parse query parameters from the request."""
    args = parse_qs(query_string.decode(), keep_blank_values=True)
    result_args = {}

    for key, values in args.items():
        if values:
            result_args[key] = values[0]

    return result_args


def get_cookies_from_headers(headers: dict[str, Any]) -> dict[str, str]:
    """Extract cookies from request headers."""
    cookies = {}
    cookie_header: str = headers.get('cookie', '')
    if cookie_header:
        for cookie in cookie_header.split(';'):
            name, value = cookie.strip().split('=')
            cookies[name] = value
    return cookies


async def send_json_response(send: Send, data: Any, status: int = 200) -> None:
    """Send a JSON response to the client."""
    await send(
        {
            'type': 'http.response.start',
            'status': status,
            'headers': [[b'content-type', b'application/json']],
        }
    )
    await send({'type': 'http.response.body', 'body': json.dumps(data, indent=2).encode()})


async def send_html_response(send: Send, html_content: bytes, status: int = 200) -> None:
    """Send an HTML response to the client."""
    await send(
        {
            'type': 'http.response.start',
            'status': status,
            'headers': [[b'content-type', b'text/html; charset=utf-8']],
        }
    )
    await send({'type': 'http.response.body', 'body': html_content})


async def app(scope: dict[str, Any], receive: Receive, send: Send) -> None:
    """Main ASGI application handler that routes requests to specific handlers.

    Args:
        scope: The ASGI connection scope.
        receive: The ASGI receive function.
        send: The ASGI send function.
    """
    assert scope['type'] == 'http'
    paths: dict[str, PathHandler] = {
        'start_enqueue': start_enqueue_endpoint,
        'sub_index': secondary_index_endpoint,
        'incapsula': incapsula_endpoint,
        'page_1': generic_response_endpoint,
        'page_2': generic_response_endpoint,
        'page_3': generic_response_endpoint,
        'set_cookies': set_cookies,
        'set_complex_cookies': set_complex_cookies,
        'cookies': get_cookies,
        'status': echo_status,
        'headers': echo_headers,
        'user-agent': echo_user_agent,
        'echo_content': echo_content,
        'sitemap.txt': echo_content,
        'sitemap.xml': echo_content,
        'sitemap.xml.gz': echo_content,
        'get': get_echo,
        'post': post_echo,
        'redirect': redirect_to_url,
        'json': hello_world_json,
        'xml': hello_world_xml,
        'robots.txt': robots_txt,
        'get_compressed': get_compressed,
    }
    path = URL(scope['path']).parts[1]
    # Route requests to appropriate handlers
    if path in paths:
        path_func = paths[path]
        await path_func(scope, receive, send)
    else:
        await hello_world(scope, receive, send)


async def get_cookies(scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests to retrieve cookies sent in the request."""
    headers = get_headers_dict(scope)
    cookies = get_cookies_from_headers(headers)
    await send_json_response(send, {'cookies': cookies})


async def set_cookies(scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests to set cookies from query parameters and redirect."""

    query_params = get_query_params(scope.get('query_string', b''))

    headers = [
        [b'content-type', b'text/plain; charset=utf-8'],
        [b'location', b'/cookies'],  # Redirect header
    ]

    for key, values in query_params.items():
        if values:  # Only add if there's at least one value
            cookie_value = f'{key}={values[0]}; Path=/'
            headers.append([b'set-cookie', cookie_value.encode()])

    await send(
        {
            'type': 'http.response.start',
            'status': 302,  # 302 Found for redirect
            'headers': headers,
        }
    )
    await send({'type': 'http.response.body', 'body': b'Redirecting to get_cookies...'})


async def hello_world(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle basic requests with a simple HTML response."""
    await send_html_response(
        send,
        HELLO_WORLD,
    )


async def hello_world_json(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle basic requests with a simple JSON response."""
    await send_json_response(
        send,
        {'hello': 'world'},
    )


async def hello_world_xml(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle basic requests with a simple XML response."""
    await send_html_response(
        send,
        b"""<?xml version="1.0"?>
            <hello>world</hello>""",
    )


async def post_echo(scope: dict[str, Any], receive: Receive, send: Send) -> None:
    """Echo back POST request details similar to httpbin.org/post."""
    # Extract basic request info
    path = scope.get('path', '')
    query_string = scope.get('query_string', b'')
    args = get_query_params(query_string)

    # Extract headers and cookies
    headers = get_headers_dict(scope)

    # Read the request body
    body = b''
    form = {}
    json_data = None
    more_body = True

    while more_body:
        message = await receive()
        if message['type'] == 'http.request':
            body += message.get('body', b'')
            more_body = message.get('more_body', False)

    # Parse body based on content type
    content_type = headers.get('content-type', '').lower()

    if body and 'application/json' in content_type:
        json_data = json.loads(body.decode())

    if body and 'application/x-www-form-urlencoded' in content_type:
        form_data = parse_qs(body.decode())
        for key, values in form_data.items():
            form[key] = values[0] if len(values) == 1 else values

    body_text = '' if form else body.decode('utf-8', errors='replace')

    # Prepare response
    response = {
        'args': args,
        'data': body_text,
        'files': {},  # Not handling multipart file uploads
        'form': form,
        'headers': headers,
        'json': json_data,
        'origin': headers.get('host', ''),
        'url': f'http://{headers["host"]}{path}',
    }

    await send_json_response(send, response)


async def echo_status(scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Echo the status code from the URL path."""
    status_code = int(scope['path'].replace('/status/', ''))
    await send(
        {
            'type': 'http.response.start',
            'status': status_code,
            'headers': [[b'content-type', b'text/plain']],
        }
    )
    await send({'type': 'http.response.body', 'body': b''})


async def echo_headers(scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Echo back the request headers as JSON."""
    headers = get_headers_dict(scope)
    await send_json_response(send, headers)


async def start_enqueue_endpoint(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests for the main page with links."""
    await send_html_response(
        send,
        START_ENQUEUE,
    )


async def secondary_index_endpoint(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests for the secondary page with links."""
    await send_html_response(
        send,
        SECONDARY_INDEX,
    )


async def incapsula_endpoint(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests for a page with an incapsula iframe."""
    await send_html_response(
        send,
        INCAPSULA,
    )


async def generic_response_endpoint(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests with a generic HTML response."""
    await send_html_response(
        send,
        GENERIC_RESPONSE,
    )


async def redirect_to_url(scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests that should redirect to a specified full URL."""
    query_params = get_query_params(scope.get('query_string', b''))

    target_url = query_params.get('url', 'http://example.com')
    status_code = int(query_params.get('status', 302))

    await send(
        {
            'type': 'http.response.start',
            'status': status_code,
            'headers': [
                [b'content-type', b'text/plain; charset=utf-8'],
                [b'location', target_url.encode()],
            ],
        }
    )
    await send({'type': 'http.response.body', 'body': f'Redirecting to {target_url}...'.encode()})


async def echo_user_agent(scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Echo back the user agent header as a response."""
    headers = get_headers_dict(scope)
    user_agent = headers.get('user-agent', 'Not provided')
    await send_json_response(send, {'user-agent': user_agent})


async def get_echo(scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Echo back GET request details similar to httpbin.org/get."""
    path = scope.get('path', '')
    query_string = scope.get('query_string', b'')
    args = get_query_params(query_string)
    headers = get_headers_dict(scope)

    origin = scope.get('client', ('unknown', 0))[0]

    host = headers.get('host', 'localhost')
    scheme = headers.get('x-forwarded-proto', 'http')
    url = f'{scheme}://{host}{path}'
    if query_string:
        url += f'?{query_string}'

    response = {
        'args': args,
        'headers': headers,
        'origin': origin,
        'url': url,
    }

    await send_json_response(send, response)


async def set_complex_cookies(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests to set specific cookies with various attributes."""

    headers = [
        [b'content-type', b'text/plain; charset=utf-8'],
        [b'set-cookie', b'basic=1; Path=/; HttpOnly; SameSite=Lax'],
        [b'set-cookie', b'withpath=2; Path=/html; SameSite=None'],
        [b'set-cookie', b'strict=3; Path=/; SameSite=Strict'],
        [b'set-cookie', b'secure=4; Path=/; HttpOnly; Secure; SameSite=Strict'],
        [b'set-cookie', b'short=5; Path=/;'],
        [b'set-cookie', b'domain=6; Path=/; Domain=.127.0.0.1;'],
    ]

    await send(
        {
            'type': 'http.response.start',
            'status': 200,
            'headers': headers,
        }
    )
    await send({'type': 'http.response.body', 'body': b'Cookies have been set!'})


async def echo_content(scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Echo back content (plain text or base64) with specified content-type."""
    query_params = get_query_params(scope.get('query_string', b''))

    content = query_params.get('content', '')
    base64_content = query_params.get('base64', '')
    c_type = query_params.get('c_type', 'text/html; charset=utf-8')

    out_content = base64.b64decode(base64_content) if base64_content else content.encode()

    await send(
        {
            'type': 'http.response.start',
            'status': 200,
            'headers': [[b'content-type', c_type.encode()]],
        }
    )

    await send({'type': 'http.response.body', 'body': out_content})


async def robots_txt(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Handle requests for the robots.txt file."""
    await send_html_response(send, ROBOTS_TXT)


async def get_compressed(_scope: dict[str, Any], _receive: Receive, send: Send) -> None:
    """Return large gzip compressed content."""

    await send(
        {
            'type': 'http.response.start',
            'status': 200,
            'headers': [[b'content-encoding', b'gzip']],
        }
    )
    await send({'type': 'http.response.body', 'body': gzip.compress(HELLO_WORLD * 1000)})


class TestServer(Server):
    """A test HTTP server implementation based on Uvicorn Server."""

    @property
    def url(self) -> URL:
        """Get the base URL of the server.

        Returns:
            A URL instance with the server's base URL.
        """
        protocol = 'https' if self.config.is_ssl else 'http'
        return URL(f'{protocol}://{self.config.host}:{self.config.port}/')

    async def serve(self, sockets: list[socket] | None = None) -> None:
        """Run the server and set up restart capability.

        Args:
            sockets: Optional list of sockets to bind to.
        """
        self.restart_requested = asyncio.Event()

        loop = asyncio.get_event_loop()
        tasks = {
            loop.create_task(super().serve(sockets=sockets)),
            loop.create_task(self.watch_restarts()),
        }
        await asyncio.wait(tasks)

    async def restart(self) -> None:
        """Request server restart and wait for it to complete.

        This method can be called from a different thread than the one the server
        is running on, and from a different async environment.
        """
        self.started = False
        self.restart_requested.set()
        while not self.started:  # noqa: ASYNC110
            await asyncio.sleep(0.2)

    async def watch_restarts(self) -> None:
        """Watch for and handle restart requests."""
        while True:
            if self.should_exit:
                return

            try:
                await asyncio.wait_for(self.restart_requested.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            self.restart_requested.clear()
            await self.shutdown()
            await self.startup()

    def run(self, sockets: list[socket] | None = None) -> None:
        """Run the server."""
        # Set the event loop policy in thread with server for Windows and Python 3.12+.
        # This is necessary because there are problems with closing connections when using `ProactorEventLoop`
        if sys.version_info >= (3, 12) and sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        super().run(sockets=sockets)


def serve_in_thread(server: TestServer) -> Iterator[TestServer]:
    """Run a server in a background thread and yield it."""
    thread = threading.Thread(target=server.run)
    thread.start()
    try:
        while not server.started:
            time.sleep(1e-3)
        yield server
    finally:
        server.should_exit = True
        thread.join()
