"""
缓存（step-05）

采用 Cache-Aside（旁路缓存）模式：先读缓存，没有再查数据库并写回缓存；
数据变化时删除缓存，而不是更新缓存。同时处理三个经典问题：

  缓存穿透  查询不存在的数据，每次都打到数据库  →  缓存空值标记 MISSING
  缓存击穿  热点 key 过期瞬间，大量请求同时回源  →  分布式锁，只放一个请求去查库
  缓存雪崩  大量 key 在同一时刻过期            →  过期时间加随机抖动

  STRING  blog:lock:{name}   分布式锁（db0）
  缓存数据本身存在 db1，通过 Django 的 cache API 读写
"""
import random
import time
import uuid

from django.core.cache import cache

from .. import redis_keys as K
from ..redis_client import get_redis

MISSING = '__missing__'   # 空值标记：数据库里确实没有
MISSING_TIMEOUT = 60      # 空值只缓存 1 分钟

# 只有锁的持有者才能删除锁：先比较 token，相等再删除，两步在 Lua 里原子执行
RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisLock:
    """最简单的分布式锁：SET key token NX PX timeout"""

    def __init__(self, name, timeout=10):
        self.key = K.lock(name)
        self.timeout_ms = int(timeout * 1000)
        # 每个持有者一个随机 token，防止误删别人的锁
        self.token = uuid.uuid4().hex

    def acquire(self):
        return bool(
            get_redis().set(self.key, self.token, nx=True, px=self.timeout_ms)
        )

    def release(self):
        return get_redis().eval(RELEASE_LOCK_SCRIPT, 1, self.key, self.token) == 1


def jitter(timeout, ratio=0.2):
    """在 timeout 的基础上随机增加 0~20%，让 key 的过期时间错开。"""
    return int(timeout * (1 + random.uniform(0, ratio)))


def _unwrap(value):
    return None if value == MISSING else value


def get_or_load(key, loader, timeout=300, lock_wait=2.0):
    """
    读缓存；未命中时调用 loader() 从数据库加载并写回缓存。
    loader 返回 None 表示数据不存在。
    """
    value = cache.get(key)
    if value is not None:
        return _unwrap(value)

    lock = RedisLock(f'cache:{key}')
    if lock.acquire():
        try:
            # 双重检查：等锁期间，可能已经有别的请求写好了缓存
            value = cache.get(key)
            if value is None:
                value = loader()
                if value is None:
                    cache.set(key, MISSING, MISSING_TIMEOUT)
                else:
                    cache.set(key, value, jitter(timeout))
                return value
            return _unwrap(value)
        finally:
            lock.release()

    # 没抢到锁：说明有别的请求正在加载，稍等片刻再读缓存
    deadline = time.monotonic() + lock_wait
    while time.monotonic() < deadline:
        time.sleep(0.05)
        value = cache.get(key)
        if value is not None:
            return _unwrap(value)
    # 等太久了（持锁的请求可能出错了），直接查数据库兜底，不写缓存
    return loader()


# ------------------------------------------------------------ 业务缓存
def get_published_post(year, month, day, slug):
    from ..models import Post

    return get_or_load(
        K.cache_post_detail(year, month, day, slug),
        lambda: Post.published.filter(
            slug=slug,
            publish__year=year,
            publish__month=month,
            publish__day=day,
        ).first(),
    )


def invalidate_post(post):
    p = post.publish
    cache.delete(K.cache_post_detail(p.year, p.month, p.day, post.slug))


def sidebar(name, loader, timeout=600):
    """
    侧边栏数据缓存。查询都很便宜，不需要锁，直接用 cache.get_or_set。
    key 中带命名空间版本号，invalidate_sidebar() 把版本号加 1，旧 key 就再也不会被读到。
    """
    ns = cache.get_or_set(K.cache_sidebar_ns(), 1, timeout=None)
    return cache.get_or_set(K.cache_sidebar(ns, name), loader, jitter(timeout))


def invalidate_sidebar():
    try:
        cache.incr(K.cache_sidebar_ns())
    except ValueError:
        # 版本号还不存在，说明也没有侧边栏缓存
        pass
