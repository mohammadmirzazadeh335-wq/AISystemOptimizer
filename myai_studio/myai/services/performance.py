"""Performance monitor (Phase 5).

Everything reported here is measured, never estimated:

* process CPU time from the operating system, divided by the wall-clock time
  between two samples;
* resident memory from ``/proc`` (Linux), ``GetProcessMemoryInfo`` (Windows) or
  ``resource`` (other POSIX systems);
* disk numbers from ``shutil.disk_usage`` on the real workspace;
* workspace sizes by walking the real files (with a hard cap so a huge folder
  cannot freeze the UI — the result then says ``truncated``).

When a platform cannot provide a number the field is ``None`` and the page says
"not available on this platform" instead of inventing a value.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..core.paths import AppPaths

logger = logging.getLogger(__name__)

#: Stop walking the workspace after this many files; the flag is reported.
MAX_WALK_FILES = 20000


@dataclass(frozen=True)
class PerformanceSnapshot:
    taken_at: float
    cpu_percent: float | None
    rss_bytes: int | None
    threads: int
    uptime_seconds: float
    disk_total: int | None
    disk_free: int | None
    workspace_bytes: int
    workspace_files: int
    workspace_truncated: bool
    db_bytes: int
    logs_bytes: int
    memory_total: int | None
    memory_available: int | None

    @property
    def disk_used(self) -> int | None:
        if self.disk_total is None or self.disk_free is None:
            return None
        return max(0, self.disk_total - self.disk_free)

    @property
    def disk_used_ratio(self) -> float | None:
        if not self.disk_total:
            return None
        return (self.disk_used or 0) / self.disk_total

    @property
    def memory_used_ratio(self) -> float | None:
        if not self.memory_total or self.memory_available is None:
            return None
        return max(0.0, min(1.0, (self.memory_total - self.memory_available) / self.memory_total))


# --------------------------------------------------------------------------- readers
def _read_linux_status() -> tuple[int | None, int | None, int | None]:
    """Return ``(rss_bytes, mem_total, mem_available)`` from /proc, or Nones."""
    rss: int | None = None
    total: int | None = None
    available: int | None = None
    try:
        with open("/proc/self/status", encoding="ascii", errors="ignore") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
    except OSError:
        rss = None
    try:
        with open("/proc/meminfo", encoding="ascii", errors="ignore") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) * 1024
    except OSError:
        total = available = None
    return rss, total, available


def _read_windows_status() -> tuple[int | None, int | None, int | None]:
    """Return ``(rss_bytes, mem_total, mem_available)`` through the Win32 API."""
    rss: int | None = None
    total: int | None = None
    available: int | None = None
    try:  # pragma: no cover - Windows only
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            rss = int(counters.WorkingSetSize)

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            total = int(status.ullTotalPhys)
            available = int(status.ullAvailPhys)
    except Exception:  # noqa: BLE001 - never let metrics break the UI
        logger.debug("windows_metrics_unavailable", exc_info=True)
    return rss, total, available


def _read_posix_status() -> tuple[int | None, int | None, int | None]:
    rss: int | None = None
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        # ru_maxrss is KiB on Linux, bytes on macOS/BSD.
        rss = int(usage.ru_maxrss) * (1 if sys.platform == "darwin" else 1024)
    except Exception:  # noqa: BLE001
        rss = None
    return rss, None, None


def _process_status() -> tuple[int | None, int | None, int | None]:
    if sys.platform.startswith("linux"):
        return _read_linux_status()
    if sys.platform.startswith("win"):
        return _read_windows_status()
    return _read_posix_status()


StatusReader = Callable[[], "tuple[int | None, int | None, int | None]"]


class PerformanceService:
    """Samples the process and the workspace; safe to call from the GUI thread."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        status_reader: StatusReader | None = None,
        cpu_clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
        started_at: float | None = None,
    ) -> None:
        self._paths = paths
        self._status_reader = status_reader or _process_status
        self._cpu_clock = cpu_clock or time.process_time
        self._wall_clock = wall_clock or time.monotonic
        self._started_at = self._wall_clock() if started_at is None else started_at
        self._last_cpu = self._cpu_clock()
        self._last_wall = self._wall_clock()
        self._lock = threading.Lock()

    @property
    def home(self) -> Path:
        """The workspace folder the page reports the size of."""
        return self._paths.home

    # ------------------------------------------------------------------ sampling
    def snapshot(self) -> PerformanceSnapshot:
        with self._lock:
            now = self._wall_clock()
            cpu_now = self._cpu_clock()
            elapsed = now - self._last_wall
            cpu_percent: float | None = None
            if elapsed > 0:
                used = max(0.0, cpu_now - self._last_cpu)
                cpu_percent = round(min(used / elapsed, 64.0) * 100.0, 1)
            self._last_cpu, self._last_wall = cpu_now, now

            rss, mem_total, mem_available = self._status_reader()
            workspace_bytes, workspace_files, truncated = self._walk(self._paths.home)
            log_bytes = self._tree_size(self._paths.logs_dir)
            db_bytes = self._db_size()

        disk_total = disk_free = None
        try:
            usage = shutil.disk_usage(self._paths.home)
            disk_total, disk_free = int(usage.total), int(usage.free)
        except OSError:
            pass

        return PerformanceSnapshot(
            taken_at=now,
            cpu_percent=cpu_percent,
            rss_bytes=rss,
            threads=threading.active_count(),
            uptime_seconds=max(0.0, now - self._started_at),
            disk_total=disk_total,
            disk_free=disk_free,
            workspace_bytes=workspace_bytes,
            workspace_files=workspace_files,
            workspace_truncated=truncated,
            db_bytes=db_bytes,
            logs_bytes=log_bytes,
            memory_total=mem_total,
            memory_available=mem_available,
        )

    # ----------------------------------------------------------------- internals
    def _db_size(self) -> int:
        total = 0
        for candidate in (
            self._paths.db_file,
            self._paths.db_file.with_name(self._paths.db_file.name + "-wal"),
            self._paths.db_file.with_name(self._paths.db_file.name + "-shm"),
        ):
            try:
                total += candidate.stat().st_size
            except OSError:
                continue
        return total

    @staticmethod
    def _walk(root: Path) -> tuple[int, int, bool]:
        total = 0
        files = 0
        truncated = False
        for _dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                if files >= MAX_WALK_FILES:
                    return total, files, True
                try:
                    stat = (Path(_dirpath) / name).stat()
                except OSError:
                    continue
                total += stat.st_size
                files += 1
        return total, files, truncated

    @staticmethod
    def _tree_size(root: Path) -> int:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                try:
                    total += (Path(dirpath) / name).stat().st_size
                except OSError:
                    continue
        return total


def format_uptime(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"
