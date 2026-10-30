"""
文章浏览量（step-03）

  STRING  blog:post:{id}:views           PV 计数，INCR 原子自增
  STRING  blog:post:{id}:seen:{visitor}  防刷标记，SET NX EX
  HLL     blog:post:{id}:uv              UV 估算，PFADD / PFCOUNT
  SET     blog:post:views:dirty          待回写数据库的文章 ID
"""
from .. import redis_keys as K
from ..models import Post
from ..redis_client import get_redis

# 同一访客在这段时间内重复访问同一篇文章，只算一次 PV
DEDUP_SECONDS = 30 * 60


def record_view(post, visitor_id):
    """记录一次浏览。返回 True 表示计入了 PV，False 表示被防刷规则过滤。"""
    r = get_redis()
    # 1. 防刷：SET NX 只在 key 不存在时写入成功，EX 让标记 30 分钟后自动消失
    first_visit = r.set(
        K.post_seen(post.id, visitor_id), 1, nx=True, ex=DEDUP_SECONDS
    )
    if not first_visit:
        return False

    # 2. 剩下的命令打包成一个 pipeline，一次网络往返全部发出去
    pipe = r.pipeline()
    # Redis 里还没有计数（第一次访问，或 Redis 数据丢失）时，用数据库里的值打底
    pipe.set(K.post_views(post.id), post.views, nx=True)
    pipe.incr(K.post_views(post.id))
    pipe.pfadd(K.post_uv(post.id), visitor_id)
    # 记下这篇文章需要回写数据库
    pipe.sadd(K.post_views_dirty(), post.id)
    pipe.execute()
    return True


def get_views(post):
    value = get_redis().get(K.post_views(post.id))
    return int(value) if value is not None else post.views


def get_uv(post):
    return get_redis().pfcount(K.post_uv(post.id))


def attach_view_counts(posts):
    """给一组文章批量设置 view_count 属性：只用一次 MGET，而不是 N 次 GET。"""
    posts = list(posts)
    if not posts:
        return posts
    values = get_redis().mget([K.post_views(p.id) for p in posts])
    for post, value in zip(posts, values):
        post.view_count = int(value) if value is not None else post.views
    return posts


def sync_views_to_db(batch_size=500):
    """把 Redis 中的浏览量回写到 Post.views，返回更新的文章数。"""
    r = get_redis()
    updated = 0
    while True:
        # SPOP 随机弹出一批 ID：弹出即删除，多个进程同时执行也不会重复处理
        ids = r.spop(K.post_views_dirty(), batch_size)
        if not ids:
            break
        values = r.mget([K.post_views(post_id) for post_id in ids])
        posts = [
            Post(id=int(post_id), views=int(value))
            for post_id, value in zip(ids, values)
            if value is not None
        ]
        Post.objects.bulk_update(posts, ['views'])
        updated += len(posts)
    return updated
