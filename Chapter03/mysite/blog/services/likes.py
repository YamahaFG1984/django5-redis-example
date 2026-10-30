"""
点赞（step-06）

  SET   blog:post:{id}:likers   文章 → 点赞用户。SADD 天然去重，SCARD 取数量
  ZSET  blog:user:{id}:likes    用户 → 点赞过的文章，按时间排序，用于「我的点赞」

两个结构是同一份关系的正反两面，写的时候用 MULTI 事务一起修改。
"""
import time

from .. import redis_keys as K
from ..models import Post
from ..redis_client import get_redis


def like(user_id, post_id):
    """点赞。返回 True 表示这次是新点赞，False 表示之前已经赞过（幂等）。"""
    pipe = get_redis().pipeline()
    pipe.sadd(K.post_likers(post_id), user_id)
    # NX：已经赞过的话不更新时间
    pipe.zadd(K.user_likes(user_id), {post_id: time.time()}, nx=True)
    added, _ = pipe.execute()
    return added == 1


def unlike(user_id, post_id):
    """取消点赞。返回 True 表示确实取消了，False 表示本来就没赞过。"""
    pipe = get_redis().pipeline()
    pipe.srem(K.post_likers(post_id), user_id)
    pipe.zrem(K.user_likes(user_id), post_id)
    removed, _ = pipe.execute()
    return removed == 1


def has_liked(user_id, post_id):
    return bool(get_redis().sismember(K.post_likers(post_id), user_id))


def like_count(post_id):
    return get_redis().scard(K.post_likers(post_id))


def attach_like_info(posts, user=None):
    """
    给一组文章设置 like_count 和 liked 属性，固定 1 次网络往返：
    N 个 SCARD + 1 个 ZMSCORE 放在同一个 pipeline 里。
    """
    posts = list(posts)
    if not posts:
        return posts
    pipe = get_redis().pipeline(transaction=False)
    for post in posts:
        pipe.scard(K.post_likers(post.id))
    if user is not None and user.is_authenticated:
        # ZMSCORE 一次查多个 member 的分数，没赞过的返回 None
        pipe.zmscore(K.user_likes(user.id), [post.id for post in posts])
    results = pipe.execute()
    liked = results[len(posts)] if len(results) > len(posts) else [None] * len(posts)
    for post, count, score in zip(posts, results, liked):
        post.like_count = count
        post.liked = score is not None
    return posts


def liked_posts(user_id, count=20):
    """用户最近点赞的文章，按点赞时间倒序。"""
    ids = [int(i) for i in get_redis().zrevrange(K.user_likes(user_id), 0, count - 1)]
    posts = Post.published.in_bulk(ids)
    return [posts[i] for i in ids if i in posts]


def remove_post(post_id):
    """文章删除时，把它从所有点赞用户的列表里移除。"""
    r = get_redis()
    user_ids = r.smembers(K.post_likers(post_id))
    pipe = r.pipeline()
    for user_id in user_ids:
        pipe.zrem(K.user_likes(user_id), post_id)
    pipe.delete(K.post_likers(post_id))
    pipe.execute()
