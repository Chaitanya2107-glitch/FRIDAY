import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from services.automation import intent, system_stats as stats
from services.automation.device_commands import match_stats_command
from services.automation.intent import try_system_action

GB = stats.GB
SMI_OUTPUT = "NVIDIA GeForce RTX 5060 Laptop GPU, 4, 3493, 8151, 55\n"


def process(pid, name, gb=0.0, cpu_seconds=0.0):
    return stats.ProcessSample(pid, name, cpu_seconds, int(gb * GB))


@pytest.fixture
def machine(monkeypatch):
    """A fake PC. Change the fields to set what psutil and nvidia-smi report."""
    m = SimpleNamespace(
        cpu=12.0,
        memory=SimpleNamespace(percent=60.0, used=9.4 * GB, total=15.7 * GB),
        battery=SimpleNamespace(percent=80, power_plugged=True, secsleft=stats.psutil.POWER_TIME_UNLIMITED),
        disk=SimpleNamespace(free=372 * GB, total=953 * GB),
        smi=SMI_OUTPUT,
        # Two process lists: CPU use is the difference between them
        snapshots=[
            [process(0, "System Idle Process", 0, 100), process(10, "chrome.exe", 1.5, 1.0),
             process(11, "chrome.exe", 1.0, 2.0), process(12, "Code.exe", 2.0, 5.0), process(13, "spotify.exe", 0.4, 1.0)],
            [process(0, "System Idle Process", 0, 200), process(10, "chrome.exe", 1.5, 3.4),
             process(11, "chrome.exe", 1.0, 2.0), process(12, "Code.exe", 2.0, 5.6), process(13, "spotify.exe", 0.4, 1.0)],
        ],
    )
    ps = stats.psutil
    monkeypatch.setattr(ps, "cpu_percent", lambda interval=None: m.cpu)
    monkeypatch.setattr(ps, "cpu_count", lambda logical=True: 24)
    monkeypatch.setattr(ps, "virtual_memory", lambda: m.memory)
    monkeypatch.setattr(ps, "sensors_battery", lambda: m.battery)
    monkeypatch.setattr(ps, "disk_usage", lambda path: m.disk)
    monkeypatch.setattr(ps, "boot_time", lambda: stats.time.time() - 2 * 3600 - 5 * 60)
    monkeypatch.setattr(stats.time, "sleep", lambda s: None)
    calls = iter(range(100))
    monkeypatch.setattr(stats, "_process_snapshot", lambda: m.snapshots[min(next(calls), 1)])
    # The CPU sample window: 0.3 s "passes" between the two process lists
    clock = iter([0.0, 0.3] + [1000.0] * 100)
    monkeypatch.setattr(stats.time, "monotonic", lambda: next(clock))

    def run(cmd, **kwargs):
        if m.smi is None:
            raise FileNotFoundError("nvidia-smi")
        return SimpleNamespace(stdout=m.smi)

    monkeypatch.setattr(stats.subprocess, "run", run)
    return m


# ── Reports ───────────────────────────────────────────────────────────────────

def test_full_report(machine):
    assert stats.report() == (
        "CPU is at 12% across 24 threads. "
        "Memory is 60% used (9.4 of 15.7 GB). "
        "Battery is at 80% and charging. "
        "RTX 5060 Laptop GPU is at 4% with 3.4 of 8.0 GB video memory used, 55°C. "
        "Drive C has 372 GB free of 953 GB. "
        "Up for 2 hours 5 minutes."
    )


def test_high_memory_names_the_biggest_apps(machine):
    machine.memory = SimpleNamespace(percent=89.0, used=14.0 * GB, total=15.7 * GB)
    report = stats.report()
    assert "Memory is 89% used (14.0 of 15.7 GB). That's running high." in report
    # chrome's two processes are added up, ".exe" is dropped, the idle process is ignored
    assert report.endswith("Using the most memory: chrome (2.5 GB), Code (2.0 GB), spotify (0.4 GB).")


def test_top_cpu_apps(machine):
    # chrome used 2.4 s of CPU time in 0.3 s on 24 threads = 33%; Code 0.6 s = 8%
    assert stats._top_apps("cpu") == [("chrome", pytest.approx(33.33, abs=0.01)),
                                       ("Code", pytest.approx(8.33, abs=0.01)), ("spotify", 0.0)]


@pytest.mark.parametrize("battery, expected", [
    (SimpleNamespace(percent=100, power_plugged=True, secsleft=-2), "Battery is at 100% and fully charged."),
    (SimpleNamespace(percent=55, power_plugged=False, secsleft=5400), "Battery is at 55%, about 1 hour 30 minutes left."),
    (SimpleNamespace(percent=15, power_plugged=False, secsleft=-1),
     "Battery is at 15%. It's getting low — plug in soon."),
    (None, "This PC has no battery."),
])
def test_battery(machine, battery, expected):
    machine.battery = battery
    assert stats.report("battery") == expected


def test_warnings(machine):
    machine.cpu = 97
    machine.smi = "NVIDIA GeForce RTX 5060 Laptop GPU, 99, 8000, 8151, 91\n"
    machine.disk = SimpleNamespace(free=8 * GB, total=953 * GB)
    assert stats.report("cpu").endswith("It's working hard.")
    assert stats.report("gpu").endswith("91°C. It's running hot.")
    assert stats.report("disk").endswith("It's nearly full.")


def test_no_nvidia_gpu(machine):
    machine.smi = None
    assert stats.report("gpu") == "I can't read the GPU (no NVIDIA GPU or driver found)."
    assert not any(line.startswith("GPU") for line in stats.menu_lines())


def test_process_listing_failure_leaves_the_apps_out(machine, monkeypatch):
    def broken():
        raise OSError("access denied")
    monkeypatch.setattr(stats, "_process_snapshot", broken)
    machine.memory = SimpleNamespace(percent=95.0, used=15 * GB, total=15.7 * GB)
    assert stats.report("memory") == "Memory is 95% used (15.0 of 15.7 GB). That's running high."


def test_real_process_listing():
    samples = stats._process_snapshot()
    assert len(samples) > 20
    me = next(s for s in samples if s.pid == stats.psutil.Process().pid)
    assert me.name.lower().startswith("python") and me.memory_bytes > 0


def test_garbled_nvidia_smi_output_is_skipped(machine):
    machine.smi = "something unexpected\n"
    assert stats._gpus() == []


def test_unknown_part_is_rejected(machine):
    with pytest.raises(ValueError):
        stats.report("fan")


def test_menu_lines(machine):
    machine.battery = SimpleNamespace(percent=80, power_plugged=True, secsleft=-2)
    assert stats.menu_lines() == [
        "CPU  12%",
        "RAM  60%  (9.4 / 15.7 GB)",
        "Battery  80%  (charging)",
        "GPU  4%, 55°C  (3.4 / 8.0 GB)",
        "Disk C:  372 GB free",
    ]


def test_real_machine_readings_work():
    # No fakes: whatever this PC has, a report comes back without errors
    assert stats.report().startswith("CPU is at ")
    assert stats.menu_lines()[0].startswith("CPU")


# ── Wordings ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, part, top", [
    ("how's my system?", None, False),
    ("hey friday, how is my laptop doing", None, False),
    ("system stats", None, False),
    ("check my pc", None, False),
    ("is my laptop ok", None, False),
    ("why is my laptop so slow", None, True),
    ("battery", "battery", False),
    ("how much battery is left", "battery", False),
    ("am i charging", "battery", False),
    ("is my laptop plugged in", "battery", False),
    ("cpu usage", "cpu", False),
    ("how busy is my cpu", "cpu", False),
    ("ram", "memory", False),
    ("memory usage", "memory", False),
    ("how much ram am i using", "memory", False),
    ("what's using my ram", "memory", True),
    ("what is eating all my memory", "memory", True),
    ("how hot is my gpu", "gpu", False),
    ("check gpu temp", "gpu", False),
    ("disk space", "disk", False),
    ("how much storage do i have left", "disk", False),
])
def test_stats_wordings(message, part, top):
    expected = {"type": "system", "action": "system_stats"}
    if part:
        expected["part"] = part
    if top:
        expected["top"] = True
    assert match_stats_command(message) == expected


@pytest.mark.parametrize("message", [
    "how much ram do i need for gaming",
    "what is ram",
    "memory",
    "what's the memory of a goldfish",
    "battery powered cars are cool",
    "is my code ok",
    "how is the weather",
    "best gpu for gaming",
    "clear chat memory",
])
def test_questions_about_hardware_stay_chat(message):
    assert match_stats_command(message) is None


def test_stats_run_without_the_ai(machine, monkeypatch):
    monkeypatch.setattr(intent, "get_provider", lambda *a, **k: pytest.fail("no AI call expected"))
    result = asyncio.run(try_system_action("how much battery is left?", "openrouter"))
    assert result.success and result.message == "Battery is at 80% and charging."
    assert result.repeatable is False  # the numbers change, so the spoken reply isn't cached


def test_tray_endpoint(machine):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    response = client.get("/api/v1/system/stats")
    assert response.status_code == 200
    assert response.json()["lines"][0] == "CPU  12%"
