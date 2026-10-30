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


# ---------------------------------------------------------------- step-05 缓存
def lock(name):
    """STRING  分布式锁，value = 持有者的随机 token，TTL 10 秒"""
    return _k('lock', name)


# 下面是 Django 缓存框架使用的 Key（存在 db1，框架会自动加上 "cache:1:" 前缀）
def cache_post_detail(year, month, day, slug):
    return f'post:detail:{year}-{month}-{day}:{slug}'


def cache_post_similar(post_id):
    return f'post:{post_id}:similar'


def cache_sidebar_ns():
    """侧边栏缓存的命名空间版本号，加 1 即可让所有侧边栏缓存失效"""
    return 'sidebar:ns'


def cache_sidebar(ns, name):
    return f'sidebar:{ns}:{name}'


# ---------------------------------------------------------------- step-06 点赞
def post_likers(post_id):
    """SET  给这篇文章点过赞的用户 ID"""
    return _k('post', post_id, 'likers')


def user_likes(user_id):
    """ZSET  用户点赞过的文章：member = 文章 ID，score = 点赞时间戳"""
    return _k('user', user_id, 'likes')


# ---------------------------------------------------------------- step-07 签到
def checkin_month(user_id, day):
    """BITMAP  用户某月的签到日历：offset = 日期 - 1，TTL 400 天"""
    return _k('checkin', user_id, day.strftime('%Y%m'))


def checkin_daily(day):
    """BITMAP  某天全站的签到情况：offset = 用户 ID，TTL 40 天"""
    return _k('checkin', 'day', day.strftime('%Y%m%d'))


def checkin_full_week(day):
    """BITMAP  临时结果：截止 day 连续 7 天都签到的用户（BITOP AND），TTL 60 秒"""
    return _k('checkin', 'week', day.strftime('%Y%m%d'))


def user_checkin_stats(user_id):
    """HASH  签到统计：total_days / streak / last_date / points"""
    return _k('user', user_id, 'checkin')


# ---------------------------------------------------------------- step-08 关注与时间线
def user_following(user_id):
    """SET  我关注的人"""
    return _k('user', user_id, 'following')


def user_followers(user_id):
    """SET  关注我的人（粉丝）"""
    return _k('user', user_id, 'followers')


def user_posts(user_id):
    """ZSET  作者的发件箱：member = 文章 ID，score = 发布时间戳"""
    return _k('user', user_id, 'posts')


def timeline(user_id):
    """ZSET  用户的收件箱（时间线），最多保留 500 条"""
    return _k('timeline', user_id)


# ---------------------------------------------------------------- step-09 推荐
def tag_posts(tag_slug):
    """SET  倒排索引：标签 → 已发布文章 ID"""
    return _k('tag', tag_slug, 'posts')


def post_tags(post_id):
    """SET  正排：文章 → 标签 slug，用来计算标签的增删"""
    return _k('post', post_id, 'tags')


def visitor_interests(visitor_id):
    """ZSET  兴趣画像：member = 标签 slug，score = 读过的该标签文章数，TTL 30 天"""
    return _k('visitor', visitor_id, 'interests')


def visitor_read(visitor_id):
    """SET  读过的文章 ID，TTL 30 天"""
    return _k('visitor', visitor_id, 'read')


def recommend_result(visitor_id):
    """ZSET  推荐结果缓存：member = 文章 ID，score = 推荐分，TTL 60 秒"""
    return _k('recommend', visitor_id)
