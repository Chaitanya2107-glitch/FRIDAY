"""
services/automation/system_stats.py

"How's my system?" — CPU, memory, battery, disk and GPU, read locally with
psutil, nvidia-smi and one Windows process-list call. Readings take up to
about half a second (CPU load has to be sampled), so callers on an event loop
should run them in a thread. Replies are plain sentences, so they work spoken too,
and they point out anything worth attention (memory nearly full, low battery,
a hot GPU) along with the apps using the most.
"""

import ctypes
import struct
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import NamedTuple

import psutil

from core.logger import logger

GB = 1024 ** 3
SYSTEM_DRIVE = "C:\\"
NVIDIA_SMI_TIMEOUT_SECONDS = 3
CPU_SAMPLE_SECONDS = 0.3

HIGH_CPU = 85
HIGH_MEMORY = 85
LOW_BATTERY = 20
HOT_GPU = 85
LOW_DISK_GB = 20
TOP_APPS = 3

# psutil.cpu_percent(None) reports the load since its previous call. That window is
# only meaningful when it's neither tiny nor hours long.
CPU_WINDOW_MIN_SECONDS = 0.5
CPU_WINDOW_MAX_SECONDS = 60
_last_cpu_reading = 0.0


@dataclass
class GpuInfo:
    name: str
    load: int
    memory_used_gb: float
    memory_total_gb: float
    temperature: int | None


def _cpu_percent() -> float:
    global _last_cpu_reading
    since = time.monotonic() - _last_cpu_reading
    if not CPU_WINDOW_MIN_SECONDS <= since <= CPU_WINDOW_MAX_SECONDS:
        psutil.cpu_percent(None)
        time.sleep(CPU_SAMPLE_SECONDS)
    _last_cpu_reading = time.monotonic()
    return psutil.cpu_percent(None)


def _gpus() -> list[GpuInfo]:
    """NVIDIA GPUs via nvidia-smi. Empty when there's no NVIDIA GPU or driver."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=NVIDIA_SMI_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.info(f"No GPU stats: {e}")
        return []
    gpus = []
    for line in out.stdout.strip().splitlines():
        try:
            name, load, used, total, temp = [part.strip() for part in line.split(",")]
            gpus.append(GpuInfo(
                name=name.replace("NVIDIA ", "").replace("GeForce ", ""),
                load=int(float(load)),
                memory_used_gb=float(used) / 1024,
                memory_total_gb=float(total) / 1024,
                temperature=int(float(temp)) if temp.replace(".", "").isdigit() else None,
            ))
        except ValueError:
            logger.warning(f"Unexpected nvidia-smi output: {line!r}")
    return gpus


class ProcessSample(NamedTuple):
    pid: int
    name: str
    cpu_seconds: float
    memory_bytes: int  # private working set — what Task Manager's Memory column shows


_SYSTEM_PROCESS_INFORMATION = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004 - (1 << 32)


def _process_snapshot() -> list[ProcessSample]:
    """
    Every process in one Windows call (~10 ms). Asking psutil process by process
    takes over a second, because protected system processes need a slow fallback.
    Offsets are for the 64-bit SYSTEM_PROCESS_INFORMATION layout.
    """
    ntdll = ctypes.WinDLL("ntdll")
    query = ntdll.NtQuerySystemInformation
    query.restype = ctypes.c_long
    query.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]

    size = 1 << 20
    while True:
        buffer = ctypes.create_string_buffer(size)
        needed = ctypes.c_ulong()
        status = query(_SYSTEM_PROCESS_INFORMATION, buffer, size, ctypes.byref(needed))
        if status != _STATUS_INFO_LENGTH_MISMATCH:
            break
        size = max(size * 2, needed.value + 65536)  # more processes started meanwhile
    if status < 0:
        raise OSError(f"NtQuerySystemInformation failed: {status & 0xFFFFFFFF:#x}")

    raw, samples, offset = buffer.raw, [], 0
    while True:
        (next_offset,) = struct.unpack_from("<I", raw, offset)
        (private_bytes,) = struct.unpack_from("<q", raw, offset + 0x08)
        user, kernel = struct.unpack_from("<qq", raw, offset + 0x28)
        name_length, _, name_pointer = struct.unpack_from("<HHxxxxQ", raw, offset + 0x38)
        (pid,) = struct.unpack_from("<Q", raw, offset + 0x50)
        name = ctypes.wstring_at(name_pointer, name_length // 2) if name_pointer else ""
        samples.append(ProcessSample(pid, name, (user + kernel) / 1e7, private_bytes))
        if not next_offset:
            return samples
        offset += next_offset


def _app_name(name: str) -> str:
    return name[:-4] if name.lower().endswith(".exe") else name


def _top_apps(kind: str) -> list[tuple[str, float]]:
    """The apps using the most memory (GB) or CPU (%), with an app's processes added up."""
    try:
        before = _process_snapshot()
    except OSError as e:
        logger.warning(f"Couldn't list processes: {e}")
        return []
    totals: dict[str, float] = defaultdict(float)

    if kind == "memory":
        for sample in before:
            if sample.pid:  # pid 0 is the idle process
                totals[_app_name(sample.name)] += sample.memory_bytes / GB
    else:
        start = time.monotonic()
        time.sleep(CPU_SAMPLE_SECONDS)
        after = _process_snapshot()
        elapsed = (time.monotonic() - start) * psutil.cpu_count()
        earlier = {(s.pid, s.name): s.cpu_seconds for s in before}
        for sample in after:
            if sample.pid and (sample.pid, sample.name) in earlier:
                used = sample.cpu_seconds - earlier[(sample.pid, sample.name)]
                totals[_app_name(sample.name)] += max(used, 0) / elapsed * 100

    totals.pop("", None)
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)[:TOP_APPS]


def _describe_top(kind: str) -> str:
    apps = _top_apps(kind)
    if not apps:
        return ""
    unit = (lambda v: f"{v:.1f} GB") if kind == "memory" else (lambda v: f"{v:.0f}%")
    listed = ", ".join(f"{name} ({unit(value)})" for name, value in apps)
    return f"Using the most {'memory' if kind == 'memory' else 'CPU'}: {listed}."


def _hours(seconds: float) -> str:
    hours, minutes = divmod(int(seconds) // 60, 60)
    minutes_text = f"{minutes} minute{'s' if minutes != 1 else ''}"
    if not hours:
        return minutes_text
    return f"{hours} hour{'s' if hours != 1 else ''} {minutes_text}"


# ── One sentence per part ─────────────────────────────────────────────────────

def _cpu() -> str:
    load = _cpu_percent()
    text = f"CPU is at {load:.0f}% across {psutil.cpu_count()} threads."
    return text + (" It's working hard." if load >= HIGH_CPU else "")


def _memory() -> str:
    mem = psutil.virtual_memory()
    text = f"Memory is {mem.percent:.0f}% used ({mem.used / GB:.1f} of {mem.total / GB:.1f} GB)."
    return text + (" That's running high." if mem.percent >= HIGH_MEMORY else "")


def _battery() -> str:
    battery = psutil.sensors_battery()
    if battery is None:
        return "This PC has no battery."
    if battery.power_plugged:
        state = "fully charged" if battery.percent >= 100 else "charging"
        return f"Battery is at {battery.percent:.0f}% and {state}."
    text = f"Battery is at {battery.percent:.0f}%"
    if battery.secsleft not in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED) and battery.secsleft > 0:
        text += f", about {_hours(battery.secsleft)} left"
    text += "."
    return text + (" It's getting low — plug in soon." if battery.percent <= LOW_BATTERY else "")


def _gpu() -> str:
    gpus = _gpus()
    if not gpus:
        return "I can't read the GPU (no NVIDIA GPU or driver found)."
    sentences = []
    for gpu in gpus:
        text = (f"{gpu.name} is at {gpu.load}% with {gpu.memory_used_gb:.1f} of "
                f"{gpu.memory_total_gb:.1f} GB video memory used")
        if gpu.temperature is not None:
            text += f", {gpu.temperature}°C"
        text += "."
        if gpu.temperature is not None and gpu.temperature >= HOT_GPU:
            text += " It's running hot."
        sentences.append(text)
    return " ".join(sentences)


def _disk() -> str:
    disk = psutil.disk_usage(SYSTEM_DRIVE)
    free = disk.free / GB
    text = f"Drive C has {free:.0f} GB free of {disk.total / GB:.0f} GB."
    return text + (" It's nearly full." if free < LOW_DISK_GB else "")


_PART_SENTENCES = {"cpu": _cpu, "memory": _memory, "battery": _battery, "gpu": _gpu, "disk": _disk}


def report(part: str | None = None, top: bool = False) -> str:
    """
    A spoken-style report of one part, or of everything when part is None.
    top=True names the apps using the most of that part (memory by default).
    """
    if part is not None and part not in _PART_SENTENCES:
        raise ValueError(f"unknown part: {part}")

    if part is None:
        text = " ".join(fn() for fn in _PART_SENTENCES.values())
        text += f" Up for {_hours(time.time() - psutil.boot_time())}."
        # Say what's hogging things when the machine is struggling
        if psutil.virtual_memory().percent >= HIGH_MEMORY or top:
            text += " " + _describe_top("memory")
        return text.strip()

    text = _PART_SENTENCES[part]()
    if top and part in ("cpu", "memory"):
        text += " " + _describe_top(part)
    elif part == "memory" and psutil.virtual_memory().percent >= HIGH_MEMORY:
        text += " " + _describe_top("memory")
    return text.strip()


def menu_lines() -> list[str]:
    """Short lines for the tray menu."""
    mem = psutil.virtual_memory()
    lines = [
        f"CPU  {_cpu_percent():.0f}%",
        f"RAM  {mem.percent:.0f}%  ({mem.used / GB:.1f} / {mem.total / GB:.1f} GB)",
    ]
    battery = psutil.sensors_battery()
    if battery is not None:
        lines.append(f"Battery  {battery.percent:.0f}%{'  (charging)' if battery.power_plugged and battery.percent < 100 else ''}")
    for gpu in _gpus():
        temp = f", {gpu.temperature}°C" if gpu.temperature is not None else ""
        lines.append(f"GPU  {gpu.load}%{temp}  ({gpu.memory_used_gb:.1f} / {gpu.memory_total_gb:.1f} GB)")
    disk = psutil.disk_usage(SYSTEM_DRIVE)
    lines.append(f"Disk C:  {disk.free / GB:.0f} GB free")
    return lines
