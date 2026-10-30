"""
所有 Redis Key 的唯一出处。

命名规则：{前缀}:{实体}:{ID}:{属性}，例如 blog:post:42:views
业务代码里不要手写 Key 字符串，统一调用这里的函数。
每一章新增的 Key 都追加在本文件中，读这个文件就能知道 Redis 里存了什么。
"""
from django.conf import settings


def _k(*parts):
    return ':'.join([settings.REDIS_KEY_PREFIX, *map(str, parts)])


# ---------------------------------------------------------------- step-03 浏览量
def post_views(post_id):
    """STRING  文章 PV 计数"""
    return _k('post', post_id, 'views')


def post_uv(post_id):
    """HYPERLOGLOG  文章 UV（独立访客数）"""
    return _k('post', post_id, 'uv')


def post_seen(post_id, visitor_id):
    """STRING  防刷标记：某访客最近看过某文章，TTL 30 分钟"""
    return _k('post', post_id, 'seen', visitor_id)


def post_views_dirty():
    """SET  浏览量有变化、等待回写数据库的文章 ID"""
    return _k('post', 'views', 'dirty')


# ---------------------------------------------------------------- step-04 排行榜
def rank_total():
    """ZSET  总榜：member = 文章 ID，score = 浏览次数"""
    return _k('rank', 'views', 'total')


def rank_daily(day):
    """ZSET  日榜，TTL 8 天"""
    return _k('rank', 'views', 'day', day.strftime('%Y%m%d'))


def rank_weekly(day):
    """ZSET  截止到 day 的 7 天榜（7 个日榜的并集），缓存 5 分钟"""
    return _k('rank', 'views', 'week', day.strftime('%Y%m%d'))
