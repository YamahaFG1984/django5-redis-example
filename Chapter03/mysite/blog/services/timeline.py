"""
关注与时间线（step-08）

  SET   blog:user:{id}:following   我关注的人
  SET   blog:user:{id}:followers   我的粉丝
  ZSET  blog:user:{id}:posts       作者发件箱（score = 发布时间）
  ZSET  blog:timeline:{id}         用户收件箱（score = 发布时间），最多 500 条

采用「写扩散」（推模式）：作者发布文章时，把文章 ID 写进每个粉丝的收件箱，
读时间线只需要读自己的一个 ZSET。
"""
from django.contrib.auth import get_user_model

from .. import redis_keys as K
from ..models import Post
from ..redis_client import get_redis

TIMELINE_MAX = 500    # 收件箱最多保留的条数
BACKFILL = 50         # 新关注时，补进时间线的作者最近文章数
FANOUT_BATCH = 1000   # 推送时每批处理的粉丝数


# ------------------------------------------------------------ 关注关系
def follow(follower_id, followee_id):
    """关注。返回 True 表示新关注。"""
    if follower_id == followee_id:
        raise ValueError("You can't follow yourself.")
    r = get_redis()
    pipe = r.pipeline()
    pipe.sadd(K.user_following(follower_id), followee_id)
    pipe.sadd(K.user_followers(followee_id), follower_id)
    added, _ = pipe.execute()
    if added:
        _backfill(r, follower_id, followee_id)
    return bool(added)


def unfollow(follower_id, followee_id):
    r = get_redis()
    pipe = r.pipeline()
    pipe.srem(K.user_following(follower_id), followee_id)
    pipe.srem(K.user_followers(followee_id), follower_id)
    removed, _ = pipe.execute()
    if removed:
        # 把这位作者的文章从我的时间线里拿掉
        post_ids = r.zrange(K.user_posts(followee_id), 0, -1)
        if post_ids:
            r.zrem(K.timeline(follower_id), *post_ids)
    return bool(removed)


def _backfill(r, user_id, author_id):
    """新关注一个作者：把他最近的文章补进我的时间线。"""
    recent = r.zrevrange(K.user_posts(author_id), 0, BACKFILL - 1, withscores=True)
    if recent:
        pipe = r.pipeline()
        pipe.zadd(K.timeline(user_id), dict(recent))
        pipe.zremrangebyrank(K.timeline(user_id), 0, -TIMELINE_MAX - 1)
        pipe.execute()


def is_following(follower_id, followee_id):
    return bool(get_redis().sismember(K.user_following(follower_id), followee_id))


def follow_counts(user_id):
    pipe = get_redis().pipeline(transaction=False)
    pipe.scard(K.user_following(user_id))
    pipe.scard(K.user_followers(user_id))
    following, followers = pipe.execute()
    return {'following': following, 'followers': followers}


def _users(ids):
    users = get_user_model().objects.in_bulk([int(i) for i in ids])
    return sorted(users.values(), key=lambda u: u.username)


def common_following(user_id, other_id):
    """我和 TA 都关注了的人：两个 following 集合求交集。"""
    return _users(get_redis().sinter(K.user_following(user_id), K.user_following(other_id)))


def mutual_follows(user_id):
    """互相关注：我关注的人 ∩ 关注我的人。"""
    return _users(get_redis().sinter(K.user_following(user_id), K.user_followers(user_id)))


# ------------------------------------------------------------ 推送与时间线
def publish(post):
    """文章发布（或更新）时：写入作者发件箱，再推送到每个粉丝的收件箱。"""
    r = get_redis()
    score = post.publish.timestamp()
    r.zadd(K.user_posts(post.author_id), {post.id: score})

    pipe = r.pipeline(transaction=False)
    # SSCAN 分批遍历粉丝，粉丝很多时也不会一次把 Redis 卡住
    for i, follower_id in enumerate(
        r.sscan_iter(K.user_followers(post.author_id), count=FANOUT_BATCH), 1
    ):
        pipe.zadd(K.timeline(follower_id), {post.id: score})
        pipe.zremrangebyrank(K.timeline(follower_id), 0, -TIMELINE_MAX - 1)
        if i % FANOUT_BATCH == 0:
            pipe.execute()
    pipe.execute()


def unpublish(post):
    """文章下线或删除：从发件箱和所有粉丝的收件箱中移除。"""
    r = get_redis()
    r.zrem(K.user_posts(post.author_id), post.id)
    pipe = r.pipeline(transaction=False)
    for follower_id in r.sscan_iter(K.user_followers(post.author_id), count=FANOUT_BATCH):
        pipe.zrem(K.timeline(follower_id), post.id)
    pipe.execute()


def get_timeline(user_id, before=None, count=10):
    """
    游标分页读取时间线。before 是上一页最后一条的 score（发布时间戳），
    返回 (文章列表, 下一页的 before 或 None)。
    """
    # "(" 表示开区间：不包含 before 本身，避免上一页最后一条重复出现
    max_score = f'({before}' if before is not None else '+inf'
    pairs = get_redis().zrevrangebyscore(
        K.timeline(user_id), max_score, '-inf', start=0, num=count, withscores=True
    )
    ids = [int(member) for member, _ in pairs]
    posts = Post.published.in_bulk(ids)
    next_before = pairs[-1][1] if len(pairs) == count else None
    return [posts[i] for i in ids if i in posts], next_before


def rebuild_outboxes():
    """从数据库重建所有作者的发件箱（Redis 数据丢失或首次上线时使用）。"""
    r = get_redis()
    pipe = r.pipeline(transaction=False)
    for post in Post.published.only('id', 'author_id', 'publish'):
        pipe.zadd(K.user_posts(post.author_id), {post.id: post.publish.timestamp()})
    pipe.execute()
