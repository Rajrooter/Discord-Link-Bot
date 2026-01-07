import logging
import re
import time
from collections import defaultdict
from threading import Lock

logger = logging.getLogger("labour_bot")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

URL_RE = re.compile(r'^(?:http|https)://', re.IGNORECASE)

def is_valid_url(url: str) -> bool:
    if not url:
        return False
    return bool(URL_RE.match(url))

class RateLimiter:
    def __init__(self):
        self._data = {}
        self._lock = Lock()

    def is_limited(self, user_id: int, key: str, cooldown: float) -> bool:
        now = time.time()
        with self._lock:
            last = self._data.get((user_id, key), 0)
            return (now - last) < cooldown

    def register(self, user_id: int, key: str):
        with self._lock:
            self._data[(user_id, key)] = time.time()

    def get_remaining(self, user_id: int, key: str, cooldown: float) -> float:
        now = time.time()
        with self._lock:
            last = self._data.get((user_id, key), 0)
            remaining = cooldown - (now - last)
            return max(0.0, remaining)

class EventCleanup:
    def __init__(self):
        self._events = defaultdict(list)
        self._lock = Lock()

    def add_event(self, channel_id: int, timestamp: float):
        with self._lock:
            self._events[channel_id].append(timestamp)

    def cleanup_old_events(self, channel_id: int, window_seconds: float):
        cutoff = time.time() - window_seconds
        with self._lock:
            lst = self._events.get(channel_id, [])
            self._events[channel_id] = [t for t in lst if t >= cutoff]

    def get_event_count(self, channel_id: int, window_seconds: float) -> int:
        self.cleanup_old_events(channel_id, window_seconds)
        with self._lock:
            return len(self._events.get(channel_id, []))

    def cleanup_memory(self):
        cutoff = time.time() - 3600
        with self._lock:
            keys = list(self._events.keys())
            for k in keys:
                self._events[k] = [t for t in self._events[k] if t >= cutoff]
                if not self._events[k]:
                    del self._events[k]
