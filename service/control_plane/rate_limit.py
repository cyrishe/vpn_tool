import threading
import time

from .errors import APIError


class LoginLimiter:
    """Bounded per-address limiter for the fixed single-worker server."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.windows = {}

    def check(self, address):
        now = self.clock()
        with self.lock:
            self.windows = {key: value for key, value in self.windows.items() if value[0] > now}
            expiry, count = self.windows.get(address, (now + 60, 0))
            if count >= 10 or (address not in self.windows and len(self.windows) >= 4096):
                raise APIError(429, "login_rate_limited", "Too many login attempts. Retry later.")
            self.windows[address] = (expiry, count + 1)
