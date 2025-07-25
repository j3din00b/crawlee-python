from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from crawlee._autoscaling import Snapshotter, SystemStatus
from crawlee._autoscaling._types import (
    ClientSnapshot,
    CpuSnapshot,
    EventLoopSnapshot,
    LoadRatioInfo,
    MemorySnapshot,
    SystemInfo,
)
from crawlee._utils.byte_size import ByteSize
from crawlee.configuration import Configuration

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def snapshotter() -> AsyncGenerator[Snapshotter, None]:
    config = Configuration(available_memory_ratio=0.25)
    async with Snapshotter.from_config(config) as snapshotter:
        yield snapshotter


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


async def test_start_stop_lifecycle() -> None:
    config = Configuration(available_memory_ratio=0.25)

    async with Snapshotter.from_config(config) as snapshotter:
        system_status = SystemStatus(snapshotter)
        system_status.get_current_system_info()
        system_status.get_historical_system_info()


def test_cpu_is_overloaded(snapshotter: Snapshotter, now: datetime) -> None:
    system_status = SystemStatus(snapshotter, cpu_overload_threshold=0.5)
    system_status._snapshotter._cpu_snapshots = Snapshotter._get_sorted_list_by_created_at(
        [
            CpuSnapshot(used_ratio=0.6, max_used_ratio=0.75, created_at=now - timedelta(minutes=3)),
            CpuSnapshot(used_ratio=0.7, max_used_ratio=0.75, created_at=now - timedelta(minutes=2)),
            CpuSnapshot(used_ratio=0.8, max_used_ratio=0.75, created_at=now - timedelta(minutes=1)),
            CpuSnapshot(used_ratio=0.9, max_used_ratio=0.75, created_at=now),
        ]
    )
    cpu_info = system_status._is_cpu_overloaded()

    assert cpu_info == LoadRatioInfo(limit_ratio=0.5, actual_ratio=0.667)
    assert cpu_info.is_overloaded is True


def test_cpu_is_not_overloaded(snapshotter: Snapshotter, now: datetime) -> None:
    system_status = SystemStatus(snapshotter, cpu_overload_threshold=0.5)
    system_status._snapshotter._cpu_snapshots = Snapshotter._get_sorted_list_by_created_at(
        [
            CpuSnapshot(used_ratio=0.7, max_used_ratio=0.75, created_at=now - timedelta(minutes=3)),
            CpuSnapshot(used_ratio=0.8, max_used_ratio=0.75, created_at=now - timedelta(minutes=2)),
            CpuSnapshot(used_ratio=0.6, max_used_ratio=0.75, created_at=now - timedelta(minutes=1)),
            CpuSnapshot(used_ratio=0.5, max_used_ratio=0.75, created_at=now),
        ]
    )
    cpu_info = system_status._is_cpu_overloaded()

    assert cpu_info == LoadRatioInfo(limit_ratio=0.5, actual_ratio=0.333)
    assert cpu_info.is_overloaded is False


def test_get_system_info(snapshotter: Snapshotter, now: datetime) -> None:
    system_status = SystemStatus(
        snapshotter,
        max_snapshot_age=timedelta(minutes=1),
        cpu_overload_threshold=0.5,
        memory_overload_threshold=0.5,
        event_loop_overload_threshold=0.5,
        client_overload_threshold=0.5,
    )

    # Add CPU snapshots
    system_status._snapshotter._cpu_snapshots = Snapshotter._get_sorted_list_by_created_at(
        [
            CpuSnapshot(used_ratio=0.6, max_used_ratio=0.75, created_at=now - timedelta(minutes=3)),
            CpuSnapshot(used_ratio=0.7, max_used_ratio=0.75, created_at=now - timedelta(minutes=2)),
            CpuSnapshot(used_ratio=0.8, max_used_ratio=0.75, created_at=now - timedelta(minutes=1)),
            CpuSnapshot(used_ratio=0.9, max_used_ratio=0.75, created_at=now),
        ]
    )

    # Add memory snapshots
    system_status._snapshotter._memory_snapshots = Snapshotter._get_sorted_list_by_created_at(
        [
            MemorySnapshot(
                current_size=ByteSize.from_gb(4),
                max_memory_size=ByteSize.from_gb(12),
                max_used_memory_ratio=0.8,
                created_at=now - timedelta(seconds=90),
                system_wide_used_size=None,
                system_wide_memory_size=None,
            ),
            MemorySnapshot(
                current_size=ByteSize.from_gb(7),
                max_memory_size=ByteSize.from_gb(8),
                max_used_memory_ratio=0.8,
                created_at=now - timedelta(seconds=60),
                system_wide_used_size=None,
                system_wide_memory_size=None,
            ),
            MemorySnapshot(
                current_size=ByteSize.from_gb(28),
                max_memory_size=ByteSize.from_gb(30),
                max_used_memory_ratio=0.8,
                created_at=now - timedelta(seconds=30),
                system_wide_used_size=None,
                system_wide_memory_size=None,
            ),
            MemorySnapshot(
                current_size=ByteSize.from_gb(48),
                max_memory_size=ByteSize.from_gb(60),
                max_used_memory_ratio=0.8,
                created_at=now,
                system_wide_used_size=None,
                system_wide_memory_size=None,
            ),
        ]
    )

    # Add event loop snapshots
    system_status._snapshotter._event_loop_snapshots = Snapshotter._get_sorted_list_by_created_at(
        [
            EventLoopSnapshot(
                delay=timedelta(milliseconds=700),
                max_delay=timedelta(milliseconds=500),
                created_at=now - timedelta(minutes=3),
            ),
            EventLoopSnapshot(
                delay=timedelta(milliseconds=600),
                max_delay=timedelta(milliseconds=500),
                created_at=now - timedelta(minutes=2),
            ),
            EventLoopSnapshot(
                delay=timedelta(milliseconds=200),
                max_delay=timedelta(milliseconds=500),
                created_at=now - timedelta(minutes=1),
            ),
            EventLoopSnapshot(
                delay=timedelta(milliseconds=100),
                max_delay=timedelta(milliseconds=500),
                created_at=now,
            ),
        ]
    )

    # Add client snapshots
    system_status._snapshotter._client_snapshots = Snapshotter._get_sorted_list_by_created_at(
        [
            ClientSnapshot(error_count=1, new_error_count=1, max_error_count=2, created_at=now - timedelta(minutes=3)),
            ClientSnapshot(error_count=2, new_error_count=1, max_error_count=2, created_at=now - timedelta(minutes=2)),
            ClientSnapshot(error_count=4, new_error_count=2, max_error_count=2, created_at=now - timedelta(minutes=1)),
            ClientSnapshot(error_count=4, new_error_count=0, max_error_count=2, created_at=now),
        ]
    )

    # Test current system info
    current_system_info = system_status.get_current_system_info()
    assert current_system_info == SystemInfo(
        cpu_info=LoadRatioInfo(limit_ratio=system_status._cpu_overload_threshold, actual_ratio=1.0),
        memory_info=LoadRatioInfo(limit_ratio=system_status._memory_overload_threshold, actual_ratio=0.5),
        event_loop_info=LoadRatioInfo(limit_ratio=system_status._event_loop_overload_threshold, actual_ratio=0),
        client_info=LoadRatioInfo(limit_ratio=system_status._client_overload_threshold, actual_ratio=0),
        created_at=current_system_info.created_at,
    )
    assert current_system_info.is_system_idle is False

    # Test historical system info
    historical_system_info = system_status.get_historical_system_info()
    assert historical_system_info == SystemInfo(
        cpu_info=LoadRatioInfo(limit_ratio=system_status._cpu_overload_threshold, actual_ratio=0.667),
        memory_info=LoadRatioInfo(limit_ratio=system_status._memory_overload_threshold, actual_ratio=0.667),
        event_loop_info=LoadRatioInfo(limit_ratio=system_status._event_loop_overload_threshold, actual_ratio=0.333),
        client_info=LoadRatioInfo(limit_ratio=system_status._client_overload_threshold, actual_ratio=0),
        created_at=historical_system_info.created_at,
    )
    assert historical_system_info.is_system_idle is False


@pytest.mark.parametrize(('client_overload_threshold', 'is_overloaded'), [(0.66, True), (0.67, False)])
def test_client_overloaded(
    *, snapshotter: Snapshotter, now: datetime, client_overload_threshold: float, is_overloaded: bool
) -> None:
    system_status = SystemStatus(
        snapshotter,
        max_snapshot_age=timedelta(minutes=1),
        client_overload_threshold=client_overload_threshold,
    )

    system_status._snapshotter._client_snapshots = Snapshotter._get_sorted_list_by_created_at(
        [
            ClientSnapshot(error_count=1, new_error_count=1, max_error_count=0, created_at=now - timedelta(minutes=3)),
            ClientSnapshot(error_count=2, new_error_count=1, max_error_count=0, created_at=now - timedelta(minutes=2)),
            ClientSnapshot(error_count=3, new_error_count=1, max_error_count=0, created_at=now - timedelta(minutes=1)),
            ClientSnapshot(error_count=3, new_error_count=0, max_error_count=0, created_at=now),
        ]
    )

    # Ratio of overloaded snapshots is 2/3 (2 minutes out of 3)
    assert system_status._is_client_overloaded().is_overloaded == is_overloaded


def test_memory_overloaded_system_wide(snapshotter: Snapshotter, now: datetime) -> None:
    """Test that system-wide memory overload is detected when system-wide memory utilization exceeds threshold."""
    system_status = SystemStatus(
        snapshotter,
        max_snapshot_age=timedelta(minutes=1),
        memory_overload_threshold=0.5,  # Set high threshold so process memory won't trigger overload
    )

    # Add memory snapshots with system-wide memory usage above threshold (97%)
    system_status._snapshotter._memory_snapshots = Snapshotter._get_sorted_list_by_created_at(
        [
            MemorySnapshot(
                current_size=ByteSize.from_gb(1),  # Process memory is low
                max_memory_size=ByteSize.from_gb(8),  # Max memory is high
                max_used_memory_ratio=0.8,  # Ratio is fine
                created_at=now - timedelta(minutes=1),
                system_wide_used_size=ByteSize.from_gb(31),  # System-wide used is high
                system_wide_memory_size=ByteSize.from_gb(32),  # System-wide total (31/32 = 96.875% < 97%)
            ),
            MemorySnapshot(
                current_size=ByteSize.from_gb(1),  # Process memory is low
                max_memory_size=ByteSize.from_gb(8),  # Max memory is high
                max_used_memory_ratio=0.8,  # Ratio is fine
                created_at=now,
                system_wide_used_size=ByteSize.from_gb(31.5),  # System-wide used is high
                system_wide_memory_size=ByteSize.from_gb(32),  # System-wide total (31.5/32 = 98.4% > 97%)
            ),
        ]
    )

    memory_info = system_status._is_memory_overloaded()

    # Should be overloaded due to system-wide memory usage exceeding 97% threshold
    assert memory_info.is_overloaded is True
    # The actual ratio should be 1.0 (the entire time period from first to second snapshot is overloaded)
    assert memory_info.actual_ratio == 1.0
    assert memory_info.limit_ratio == 0.5
