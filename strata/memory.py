"""CPU allocation accounting; estimates exclude driver/depth/VBO overhead."""
from collections import deque
import time


class MemoryBudget:
    def __init__(self, limit_bytes=5 * 1024 ** 3):
        self.limit_bytes = int(limit_bytes)
        self.live_bytes = self.peak_bytes = 0
        self.allocations = {}
        self.timings = deque(maxlen=256)
        self._serial = 0

    def check(self, size):
        """Check a compound allocation before publishing any owned textures."""
        size = int(size)
        if size < 0 or self.live_bytes + size > self.limit_bytes:
            raise MemoryError(f"GPU texture budget exceeded: {(self.live_bytes + size) / 1024 ** 2:.0f} MiB requested, "
                              f"{self.limit_bytes / 1024 ** 2:.0f} MiB budget")
        return size

    def reserve(self, size, owner="texture"):
        size = self.check(size)
        self._serial += 1
        self.allocations[self._serial] = (size, owner)
        self.live_bytes += size
        self.peak_bytes = max(self.live_bytes, self.peak_bytes)
        return self._serial

    def release(self, token):
        self.live_bytes -= self.allocations.pop(token, (0, None))[0]

    def report(self):
        owners = {}
        for size, owner in self.allocations.values():
            owners[owner] = owners.get(owner, 0) + size
        return {"live_bytes": self.live_bytes, "peak_bytes": self.peak_bytes,
                "limit_bytes": self.limit_bytes, "allocations": len(self.allocations), "owners": owners, "timings": list(self.timings)}
