from __future__ import annotations

import os
from functools import lru_cache

from redis import Redis
from rq import Queue


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    redis_url = os.getenv(
        "REDIS_URL",
        "redis://redis:6379/0",
    )
    connection = Redis.from_url(redis_url)
    return Queue(
        "vision",
        connection=connection,
        default_timeout=600,
    )