import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from app.core.config.settings import settings


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self, redis_url: str):
        self._mem: dict = defaultdict(deque)
        self._redis = None
        if redis_url:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(redis_url)

    async def hit(self, key: str, limit: int, window: int) -> bool:
        if self._redis is not None:
            bucket = f"rl:{key}:{int(time.time() // window)}"
            count = await self._redis.incr(bucket)
            if count == 1:
                await self._redis.expire(bucket, window)
            return count <= limit
        now = time.time()
        q = self._mem[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


limiter = RateLimiter(settings.redis_url)


async def enforce(key: str, limit: int, window: int) -> None:
    if not await limiter.hit(key, limit, window):
        raise HTTPException(status_code=429, detail="Muitas requisições. Tente novamente em instantes.")


def rate_limit(scope: str, limit: int, window: int):
    async def dependency(request: Request):
        await enforce(f"{scope}:{client_ip(request)}", limit, window)
    return Depends(dependency)
