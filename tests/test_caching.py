from unittest.mock import MagicMock, AsyncMock
import pytest

from gallery import caching


@pytest.fixture
def redis(monkeypatch):
    _cache = {}
    mock = MagicMock()
    mock.exists = AsyncMock(side_effect=_cache.__contains__)
    mock.get = AsyncMock(side_effect=_cache.__getitem__)
    # redis only stores byte strings, even if it accepts both
    def cacheset(key, val):
        if isinstance(val, str):
            val = val.encode('utf-8')
        _cache[key] = val
    mock.set = AsyncMock(side_effect=cacheset)
    mock.delete = AsyncMock(side_effect=_cache.__delitem__)
    mock.dbsize = AsyncMock(side_effect=_cache.__len__)
    monkeypatch.setattr(caching.RedisInstance, 'redis', mock)
    yield mock


async def test_cache(redis):
    mocker = MagicMock()

    cache = caching.RedisInstance()

    await cache.set('foo', 'bar')
    assert (await cache.get('foo')) == 'bar'
    assert await cache.contains('foo')
    await cache.delete('foo')
    assert not (await cache.contains('foo'))
    with pytest.raises(KeyError):
        await cache.get('foo')

    await cache.set('bar', {'a': 1, 'b': 2})
    assert (await cache.get('bar')) == {'a': 1, 'b': 2}
    assert await cache.contains('bar')
    await cache.delete('bar')
    assert not (await cache.contains('bar'))
    with pytest.raises(KeyError):
        await cache.get('bar')
