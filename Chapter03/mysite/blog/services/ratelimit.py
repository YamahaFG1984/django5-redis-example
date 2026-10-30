"""
接口限流（step-10）

两种算法，都用 Lua 脚本把「读计数 → 判断 → 写计数」合成一个原子操作：

  固定窗口  STRING  blog:ratelimit:fixed:{scope}:{ident}:{窗口序号}   INCR + EXPIRE
  滑动窗口  ZSET    blog:ratelimit:sliding:{scope}:{ident}             每次请求记一条，按时间删旧的
"""
import time
import uuid
from dataclasses import dataclass
from functools import wraps

from django.shortcuts import render

from .. import redis_keys as K
from ..redis_client import get_redis

FIXED_WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    -- 窗口里的第一个请求负责设置过期时间
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

SLIDING_WINDOW_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
-- 1. 删掉已经滑出窗口的请求记录
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
-- 2. 窗口内还有名额：记下这次请求
if redis.call('ZCARD', KEYS[1]) < limit then
    redis.call('ZADD', KEYS[1], now, ARGV[4])
    redis.call('PEXPIRE', KEYS[1], window)
    return {1, limit - redis.call('ZCARD', KEYS[1]), 0}
end
-- 3. 没有名额：最早的那条记录滑出窗口后才能再请求
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
return {0, 0, tonumber(oldest[2]) + window - now}
"""


@dataclass
class Decision:
    allowed: bool
    remaining: int
    retry_after: int   # 秒；允许时为 0


def _run(script, keys, args):
    # register_script 在本地算好 SHA1，调用时先发 EVALSHA，
    # Redis 里还没有这个脚本时自动退回 SCRIPT LOAD 再执行
    return get_redis().register_script(script)(keys=keys, args=args)


def fixed_window(scope, ident, limit, window, now=None):
    now = time.time() if now is None else now
    window_index = int(now // window)
    count = _run(
        FIXED_WINDOW_SCRIPT,
        [K.ratelimit_fixed(scope, ident, window_index)],
        [window],
    )
    if count <= limit:
        return Decision(True, limit - count, 0)
    window_end = (window_index + 1) * window
    return Decision(False, 0, int(window_end - now) + 1)


def sliding_window(scope, ident, limit, window, now=None):
    now_ms = int((time.time() if now is None else now) * 1000)
    allowed, remaining, retry_ms = _run(
        SLIDING_WINDOW_SCRIPT,
        [K.ratelimit_sliding(scope, ident)],
        # 每个请求一个唯一 member，避免同一毫秒的两次请求互相覆盖
        [now_ms, window * 1000, limit, f'{now_ms}-{uuid.uuid4().hex[:8]}'],
    )
    return Decision(bool(allowed), remaining, -(-retry_ms // 1000))  # 向上取整


def client_ip(request):
    # 部署在 Nginx 等反向代理后面时，应改为读取可信代理设置的 X-Forwarded-For
    return request.META.get('REMOTE_ADDR', 'unknown')


def rate_limit(scope, limit, window, algorithm='sliding', methods=('POST',)):
    """视图装饰器：同一 IP 在 window 秒内最多请求 limit 次，超出返回 429。"""
    check = sliding_window if algorithm == 'sliding' else fixed_window

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method in methods:
                decision = check(scope, client_ip(request), limit, window)
                if not decision.allowed:
                    response = render(
                        request,
                        'blog/rate_limited.html',
                        {'retry_after': decision.retry_after},
                        status=429,
                    )
                    response['Retry-After'] = str(decision.retry_after)
                    return response
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
