"""One shared, nonblocking sample per second, independent of HTTP worker threads."""
from copy import deepcopy
import math
import threading
import time

import psutil


def number(value, low=0, high=float('inf')):
    return min(high, max(low, float(value))) if isinstance(value, (int, float)) and math.isfinite(value) else None


class Stats:
    def __init__(self, reader=psutil, clock=time.monotonic, wall=time.time, gpu=lambda: None):
        self.reader, self.clock, self.wall, self.gpu = reader, clock, wall, gpu
        self.lock = threading.Lock()
        self.at, self.cached, self.previous = None, None, None

    def snapshot(self, request=None):
        with self.lock:
            now = self.clock()
            if self.at is not None and 0 <= now - self.at < 1:
                return deepcopy(self.cached)
            cpu, network, battery, ram = None, None, None, None
            try:
                times = self.reader.cpu_times()
                # Linux guest time is already counted in user/nice time.
                total = sum(times) - getattr(times, 'guest', 0) - getattr(times, 'guest_nice', 0)
                idle = times.idle + getattr(times, 'iowait', 0)
                counters = self.reader.net_io_counters()
                if self.previous:
                    at, old_total, old_idle, sent, received = self.previous
                    delta, elapsed = total - old_total, now - at
                    cpu = number(100 * (1 - (idle - old_idle) / delta), high=100) if delta > 0 else 0.0
                    if elapsed > 0:
                        network = {'upload_bps': max(0, counters.bytes_sent - sent) / elapsed,
                                   'download_bps': max(0, counters.bytes_recv - received) / elapsed}
                self.previous = (now, total, idle, counters.bytes_sent, counters.bytes_recv)
            except (OSError, AttributeError, RuntimeError):
                pass
            try:
                memory = self.reader.virtual_memory()
                ram = {'percent': number(memory.percent, high=100), 'used_bytes': memory.used, 'total_bytes': memory.total}
            except (OSError, AttributeError, RuntimeError):
                pass
            try:
                power = self.reader.sensors_battery()
                if power:
                    battery = {'percent': number(power.percent, high=100), 'plugged': bool(power.power_plugged),
                               'charging': bool(power.power_plugged and power.percent < 100)}
            except (OSError, AttributeError, RuntimeError):
                pass
            self.at = now
            self.cached = {'sampled_at': self.wall(), 'cpu_percent': cpu, 'ram': ram, 'battery': battery,
                           'gpu': self.gpu(), 'network': network}
            return deepcopy(self.cached)
