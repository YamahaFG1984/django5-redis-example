"""
热门排行榜（step-04）

  ZSET  blog:rank:views:total             总榜
  ZSET  blog:rank:views:day:{yyyymmdd}    日榜，保留 8 天
  ZSET  blog:rank:views:week:{yyyymmdd}   周榜 = 最近 7 个日榜 ZUNIONSTORE，缓存 5 分钟
"""
from datetime import timedelta

from django.utils import timezone

from .. import redis_keys as K
from ..models import Post
from ..redis_client import get_redis

DAILY_TTL = 8 * 24 * 3600
WEEKLY_CACHE_SECONDS = 5 * 60
PERIODS = ('day', 'week', 'total')


def record_view(post_id, day=None, amount=1):
    """文章热度 +amount：总榜和当天的日榜同时累加。"""
    day = day or timezone.localdate()
    daily = K.rank_daily(day)
    pipe = get_redis().pipeline()
    pipe.zincrby(K.rank_total(), amount, post_id)
    pipe.zincrby(daily, amount, post_id)
    # 每次都刷新过期时间也没关系：日榜最后一次写入后 8 天被删除
    pipe.expire(daily, DAILY_TTL)
    pipe.execute()


def _weekly_key(today):
    """把最近 7 天的日榜合并成周榜。结果缓存 5 分钟，避免每次请求都重新合并。"""
    r = get_redis()
    key = K.rank_weekly(today)
    if not r.exists(key):
        days = [K.rank_daily(today - timedelta(days=i)) for i in range(7)]
        pipe = r.pipeline()
        # 同一篇文章在多个日榜中的 score 相加（默认 AGGREGATE SUM）
        pipe.zunionstore(key, days)
        pipe.expire(key, WEEKLY_CACHE_SECONDS)
        pipe.execute()
    return key


def _key_for(period, today):
    if period == 'day':
        return K.rank_daily(today)
    if period == 'week':
        return _weekly_key(today)
    return K.rank_total()


def top_ids(period='total', count=10, today=None):
    """返回 [(文章 ID, 热度), ...]，按热度从高到低。"""
    today = today or timezone.localdate()
    pairs = get_redis().zrevrange(
        _key_for(period, today), 0, count - 1, withscores=True
    )
    return [(int(member), int(score)) for member, score in pairs]


def top_posts(period='total', count=10, today=None):
    """返回已发布的热门文章列表，每篇文章带上 score 属性。"""
    # 多取一些，防止榜单里有已下线的文章导致数量不够
    pairs = top_ids(period, count * 2, today)
    posts = Post.published.in_bulk([post_id for post_id, _ in pairs])
    result = []
    for post_id, score in pairs:
        post = posts.get(post_id)
        if post is not None:
            post.score = score
            result.append(post)
    return result[:count]


def remove_post(post_id, today=None):
    """文章下线或删除时，从所有榜单中移除。"""
    today = today or timezone.localdate()
    pipe = get_redis().pipeline()
    pipe.zrem(K.rank_total(), post_id)
    for i in range(8):
        day = today - timedelta(days=i)
        pipe.zrem(K.rank_daily(day), post_id)
        pipe.zrem(K.rank_weekly(day), post_id)
    pipe.execute()
