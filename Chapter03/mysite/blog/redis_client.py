"""
Redis 连接管理。

整个进程共享一个连接池（ConnectionPool）。get_redis() 每次返回一个新的
Redis 对象，但它很轻量，真正的 TCP 连接由连接池负责复用。
"""
import redis
from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver

_pool = None


def get_redis():
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            # 让命令返回 str 而不是 bytes，模板和业务代码里更方便
            decode_responses=True,
        )
    return redis.Redis(connection_pool=_pool)


def reset_pool():
    """断开并丢弃连接池，下次 get_redis() 时按最新配置重建。"""
    global _pool
    if _pool is not None:
        _pool.disconnect()
    _pool = None


@receiver(setting_changed)
def _on_setting_changed(setting, **kwargs):
    # 测试里用 override_settings 切换 REDIS_URL 时，让连接池跟着切换
    if setting == 'REDIS_URL':
        reset_pool()
