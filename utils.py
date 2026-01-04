import logging
import time
from urllib.parse import urlparse
from typing import Optional
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("labour_bot")


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            return False
        if result.scheme not in ['http', 'https']:
            return False
        private_ips = ['localhost', '127.0.0.1', '0.0.0.0', '192.168', '10.0', '172.16']
        if any(ip in result.netloc.lower() for ip in private_ips):
            return False
        return True
    except Exception as e:
        logger.warning(f"URL validation error for {url}: {e}")
        return False


class RateLimiter:
    def __init__(self):
        self.cooldowns = defaultdict(lambda: defaultdict(float))

    def is_limited(self, user_id: int, command: str, cooldown: float = 3.0) -> bool:
        now = time.time()
        last_used = self.cooldowns[user_id][command]

        if now - last_used < cooldown:
            return True

        self.cooldowns[user_id][command] = now
        return False

    def get_remaining(self, user_id: int, command: str, cooldown: float = 3.0) -> float:
        now = time.time()
        last_used = self.cooldowns[user_id][command]
        remaining = cooldown - (now - last_used)
        return max(0, remaining)


class EventCleanup:
    def __init__(self, max_entries: int = 5000):
        self.events = {}
        self.max_entries = max_entries

    def add_event(self, channel_id: int, timestamp: float):
        if channel_id not in self.events:
            self.events[channel_id] = []
        self.events[channel_id].append(timestamp)

    def cleanup_old_events(self, channel_id: int, window_seconds: float):
        if channel_id not in self.events:
            return

        now = time.time()
        self.events[channel_id] = [
            ts for ts in self.events[channel_id]
            if now - ts <= window_seconds
        ]

        if not self.events[channel_id]:
            del self.events[channel_id]

    def get_event_count(self, channel_id: int, window_seconds: float) -> int:
        if channel_id not in self.events:
            return 0

        now = time.time()
        count = sum(1 for ts in self.events[channel_id] if now - ts <= window_seconds)
        return count

    def cleanup_memory(self):
        if len(self.events) > self.max_entries:
            oldest_channel = min(self.events.keys(), key=lambda x: len(self.events[x]))
            del self.events[oldest_channel]
