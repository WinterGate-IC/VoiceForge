"""Adaptive resource governor for long-form rendering.

Rendering a long script means many independent Edge requests. They are
network-bound, so a handful of threads cuts the wait dramatically without
pinning the CPU the way parallel synthesis would. The catch is that every
machine has a different comfortable limit, and that limit can change while a
job is running because the user opened a game, a browser, or a build.

This module answers two questions:

    choose_workers(...)   how many parts should we start with?
    Governor              how many may run *right now*, and when do we slow
                          down or speed back up?

Everything is sampled with the standard library (no psutil dependency) and is
strictly best-effort: if a measurement fails, the neutral answer is used and
rendering continues. When the machine is under real pressure the governor
falls all the way back to one part at a time - the old, slow, safe behaviour -
and only tries to ramp up again after a run of healthy parts.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

# Manual override ceiling. Auto mode stays far below this.
MAX_WORKERS = 8
AUTO_MAX_WORKERS = 4
AUTO_MIN_WORKERS = 1

# Above these the governor actively backs off.
CPU_HOT = 90.0
CPU_WARM = 72.0
MEMORY_HOT = 92.0
MEMORY_WARM = 82.0
FREE_MB_HOT = 384.0
FREE_MB_WARM = 900.0

# Healthy parts needed before stepping back up one worker.
RAMP_AFTER = 3


@dataclass(frozen=True)
class Snapshot:
    """One best-effort reading of the machine.

    A negative value means "could not measure", never "zero load".
    """

    cpu_percent: float = -1.0
    memory_percent: float = -1.0
    available_mb: float = -1.0
    total_mb: float = -1.0
    cores: int = 1
    load1: float = -1.0
    taken_at: float = 0.0

    def known(self) -> bool:
        return self.cpu_percent >= 0 or self.memory_percent >= 0


# --------------------------------------------------------------- sampling
def _windows_cpu() -> float:
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    kernel32 = ctypes.windll.kernel32

    def read() -> tuple[int, int, int]:
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        ok = kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel),
                                     ctypes.byref(user))
        if not ok:
            raise OSError("GetSystemTimes failed")
        to_int = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        return to_int(idle), to_int(kernel), to_int(user)

    idle1, kernel1, user1 = read()
    time.sleep(0.08)
    idle2, kernel2, user2 = read()
    idle_delta = idle2 - idle1
    total_delta = (kernel2 - kernel1) + (user2 - user1)
    if total_delta <= 0:
        return -1.0
    return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))


def _linux_cpu() -> float:
    def read() -> tuple[int, int]:
        with open("/proc/stat", "r", encoding="ascii") as handle:
            fields = handle.readline().split()[1:]
        values = [int(value) for value in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return idle, sum(values)

    idle1, total1 = read()
    time.sleep(0.08)
    idle2, total2 = read()
    total_delta = total2 - total1
    if total_delta <= 0:
        return -1.0
    return max(0.0, min(100.0, 100.0 * (1.0 - (idle2 - idle1) / total_delta)))


def _cpu_percent() -> float:
    try:
        if sys.platform.startswith("win"):
            return _windows_cpu()
        if sys.platform.startswith("linux"):
            return _linux_cpu()
        load = os.getloadavg()[0]
        cores = max(1, os.cpu_count() or 1)
        return max(0.0, min(100.0, 100.0 * load / cores))
    except Exception:
        return -1.0


def _memory() -> tuple[float, float, float]:
    """(percent used, available MB, total MB); -1 where unknown."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
                    ctypes.byref(status)):
                return -1.0, -1.0, -1.0
            total_mb = status.ullTotalPhys / (1024 * 1024)
            available_mb = status.ullAvailPhys / (1024 * 1024)
            return float(status.dwMemoryLoad), available_mb, total_mb

        if sys.platform.startswith("linux"):
            values: dict[str, float] = {}
            with open("/proc/meminfo", "r", encoding="ascii") as handle:
                for line in handle:
                    key, _, rest = line.partition(":")
                    parts = rest.split()
                    if parts:
                        values[key] = float(parts[0])
            total_kb = values.get("MemTotal", -1.0)
            available_kb = values.get("MemAvailable", -1.0)
            if total_kb <= 0:
                return -1.0, -1.0, -1.0
            total_mb = total_kb / 1024
            available_mb = available_kb / 1024 if available_kb > 0 else -1.0
            used = (100.0 * (total_mb - available_mb) / total_mb
                    if available_mb > 0 else -1.0)
            return used, available_mb, total_mb
    except Exception:
        pass
    return -1.0, -1.0, -1.0


def snapshot() -> Snapshot:
    """Best-effort CPU, memory and core count for this machine."""
    cpu = _cpu_percent()
    memory_percent, available_mb, total_mb = _memory()
    try:
        load1 = float(os.getloadavg()[0])
    except (AttributeError, OSError):
        load1 = -1.0
    return Snapshot(
        cpu_percent=cpu,
        memory_percent=memory_percent,
        available_mb=available_mb,
        total_mb=total_mb,
        cores=max(1, int(os.cpu_count() or 1)),
        load1=load1,
        taken_at=time.monotonic(),
    )


def describe(info: Snapshot | None = None) -> str:
    """One plain sentence for the Settings dialog and status lines."""
    info = info or snapshot()
    bits = [f"{info.cores} CPU core" + ("s" if info.cores != 1 else "")]
    if info.memory_percent >= 0:
        bits.append(f"memory {info.memory_percent:.0f}% used")
        if info.available_mb >= 0:
            bits.append(f"{info.available_mb / 1024:.1f} GB free")
    if info.cpu_percent >= 0:
        bits.append(f"CPU {info.cpu_percent:.0f}%")
    return ", ".join(bits)


# --------------------------------------------------------------- decisions
def _clamp_workers(value: int, parts: int) -> int:
    return max(1, min(MAX_WORKERS, int(parts), int(value)))


def choose_workers(parts: int, requested: int = 0, adaptive: bool = True,
                   info: Snapshot | None = None) -> int:
    """How many parts to start with.

    `requested` is the user's manual setting (0 means automatic). A manual
    value is honoured even when the machine is busy - the user asked for it -
    but it is still capped by the number of parts and MAX_WORKERS.

    Automatic mode is deliberately conservative: Edge is waiting on HTTPS, so
    beyond four requests the gain flattens and the chance of rate-limiting
    rises. A hot CPU or low memory drops it immediately to one.
    """
    parts = max(1, int(parts))
    requested = max(0, int(requested or 0))
    if requested:
        return _clamp_workers(requested, parts)
    if not adaptive:
        return 1

    info = info or snapshot()
    cores = max(1, int(info.cores or 1))
    if cores <= 2:
        target = 2
    else:
        target = min(AUTO_MAX_WORKERS, max(AUTO_MIN_WORKERS, cores - 1))

    if info.memory_percent >= MEMORY_HOT or 0 <= info.available_mb < FREE_MB_HOT:
        target = 1
    elif (info.memory_percent >= MEMORY_WARM
          or 0 <= info.available_mb < FREE_MB_WARM):
        target = min(target, 2)

    if info.cpu_percent >= CPU_HOT:
        target = 1
    elif info.cpu_percent >= CPU_WARM:
        target = min(target, 2)
    elif info.cpu_percent >= 55:
        target = min(target, 3)

    return _clamp_workers(target, parts)


class Governor:
    """Live worker budget that backs off under load and ramps back up.

    `observe(ok)` is called once per finished part. It returns a short notice
    when the budget changed, which the renderer forwards to the UI so the user
    can see *why* the wait estimate moved.
    """

    def __init__(self, parts: int, requested: int = 0, adaptive: bool = True,
                 snapshot_fn: Callable[[], Snapshot] | None = None) -> None:
        self.parts = max(1, int(parts))
        self.requested = max(0, int(requested or 0))
        self.adaptive = bool(adaptive)
        # Tests inject a deterministic sampler; production uses the real one.
        self._sample = snapshot_fn or snapshot
        self.snapshot = self._read()
        self.max_workers = choose_workers(
            self.parts, self.requested, self.adaptive, self.snapshot)
        self.workers = self.max_workers
        self.healthy = 0
        self.failures = 0
        self.notices: list[str] = []
        self._last_notice = ""
        self._lock = threading.Lock()

    # -- helpers -------------------------------------------------------
    def _read(self) -> Snapshot:
        try:
            value = self._sample()
            return value if isinstance(value, Snapshot) else Snapshot()
        except Exception:
            return Snapshot()

    def note(self, message: str) -> str:
        message = (message or "").strip()
        if not message:
            return ""
        if message != self._last_notice:
            self.notices.append(message)
            self._last_notice = message
        return message

    def limit(self) -> int:
        return max(1, min(self.workers, self.parts))

    def reason(self) -> str:
        if not self.adaptive:
            return "Adaptive rendering is off - one part at a time."
        if self.requested:
            return f"Using your fixed setting of {self.workers}."
        if self.workers <= 1:
            return "One part at a time until the machine is comfortable again."
        return (f"{self.workers} parts at a time"
                f" (up to {self.max_workers} on this machine).")

    def _pressure(self) -> str:
        info = self.snapshot
        if 0 <= info.available_mb < FREE_MB_HOT:
            return (f"Low memory ({info.available_mb:.0f} MB free) - slowing "
                    "down until the device recovers.")
        if info.memory_percent >= MEMORY_HOT:
            return (f"Memory is {info.memory_percent:.0f}% full - slowing down "
                    "until the device recovers.")
        if info.cpu_percent >= CPU_HOT:
            return (f"CPU is at {info.cpu_percent:.0f}% - slowing down so the "
                    "device stays responsive.")
        if 0 <= info.memory_percent >= MEMORY_WARM:
            return (f"Memory is {info.memory_percent:.0f}% used - keeping the "
                    "load light.")
        if info.cpu_percent >= CPU_WARM:
            return (f"CPU is at {info.cpu_percent:.0f}% - keeping the load "
                    "light.")
        return ""

    # -- live budget ---------------------------------------------------
    def observe(self, ok: bool, _error: object | None = None) -> str:
        """Record one finished part and adjust the budget."""
        if not self.adaptive or self.requested:
            # A fixed setting is the user's call; only a failure is worth
            # noting, and the renderer already retries the part itself.
            return ""
        with self._lock:
            return self._observe(ok)

    def _observe(self, ok: bool) -> str:
        # Sampling sleeps briefly; don't do it for every part. Once a second
        # and a half is enough to notice a machine that is heating up.
        now = time.monotonic()
        if now - self.snapshot.taken_at > 1.5 or not self.snapshot.known():
            self.snapshot = self._read()

        if not ok:
            self.failures += 1
            self.healthy = 0
            if self.workers > 1:
                self.workers = max(1, self.workers // 2)
                return self.note(
                    f"A part failed - slowing to {self.workers} part"
                    f"{'s' if self.workers != 1 else ''} at a time while the "
                    "device and connection settle.")
            return ""

        self.failures = 0
        self.healthy += 1
        pressure = self._pressure()
        if pressure:
            self.healthy = 0
            if self.workers > 1:
                self.workers = max(1, self.workers - 1)
            return self.note(pressure)

        if self.workers < self.max_workers and self.healthy >= RAMP_AFTER:
            self.workers += 1
            self.healthy = 0
            return self.note(
                f"Device is stable again - back to {self.workers} parts at a "
                "time.")
        return ""

    def status_fields(self) -> dict[str, object]:
        """The bits every progress event carries about the current budget."""
        return {
            "workers": self.limit(),
            "max_workers": self.max_workers,
            "worker_note": self.reason(),
            "adaptive": self.adaptive,
        }
