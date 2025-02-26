import json
import logging

from redis.backoff import ExponentialBackoff
from redis.asyncio.retry import Retry
from redis.asyncio import Redis
from redis.exceptions import (
   BusyLoadingError,
   ConnectionError,
   TimeoutError
)

from .config import ENV


class RedisInstance:
    redis: Redis | None = None
    def __init__(self):
        if not RedisInstance.redis:
            self.restart()
    
    async def close(self):
        if RedisInstance.redis:
            await RedisInstance.redis.close()
            RedisInstance.redis = None

    @classmethod
    def restart(cls):
        # Run 3 retries with exponential backoff strategy
        retry = Retry(ExponentialBackoff(), 3)
        # Redis client with retries on custom errors
        r = Redis(host=ENV.REDIS_HOST, port=ENV.REDIS_PORT, protocol=3, retry=retry, retry_on_error=[BusyLoadingError, ConnectionError, TimeoutError])
        cls.redis = r

    async def contains(self, name):
        assert self.redis is not None
        return bool(await self.redis.exists(str(name)))

    async def get(self, name):
        logging.debug('Cache-get: %s', name)
        assert self.redis is not None
        val = await self.redis.get(str(name))
        if not val:
            raise KeyError('not found')
        else:
            return json.loads(val.decode('utf-8'))

    async def set(self, name, val):
        logging.debug('Cache-set: %s', name)
        assert self.redis is not None
        await self.redis.set(str(name), json.dumps(val))

    async def delete(self, name):
        logging.debug('Cache-delete: %s', name)
        assert self.redis is not None
        await self.redis.delete(str(name))

    async def count(self):
        assert self.redis is not None
        return await self.redis.dbsize()
