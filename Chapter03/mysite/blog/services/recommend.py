"""
个性化推荐（step-09）

基于标签的内容推荐：
  1. 访客每读一篇文章，这篇文章的每个标签在他的兴趣画像里 +1
  2. 取兴趣最高的几个标签，把对应的「标签 → 文章」集合按兴趣分加权合并
  3. 去掉读过的文章；数量不够时用热榜补齐（冷启动）

  SET   blog:tag:{slug}:posts         倒排索引（随文章和标签变化维护）
  SET   blog:post:{id}:tags           正排索引
  ZSET  blog:visitor:{vid}:interests  兴趣画像，TTL 30 天
  SET   blog:visitor:{vid}:read       已读文章，TTL 30 天
  ZSET  blog:recommend:{vid}          推荐结果缓存，TTL 60 秒
"""
from .. import redis_keys as K
from ..models import Post
from ..redis_client import get_redis
from . import ranking

PROFILE_TTL = 30 * 24 * 3600
RESULT_TTL = 60
TOP_TAGS = 5


# ------------------------------------------------------------ 标签索引
def _sync_index(post_id, new_tags):
    r = get_redis()
    old_tags = r.smembers(K.post_tags(post_id))
    pipe = r.pipeline()
    for slug in old_tags - new_tags:
        pipe.srem(K.tag_posts(slug), post_id)
    for slug in new_tags - old_tags:
        pipe.sadd(K.tag_posts(slug), post_id)
    pipe.delete(K.post_tags(post_id))
    if new_tags:
        pipe.sadd(K.post_tags(post_id), *new_tags)
    pipe.execute()


def index_post(post):
    """文章保存或标签变化时调用：已发布的文章进入索引，其他状态移出。"""
    if post.status == Post.Status.PUBLISHED:
        tags = set(post.tags.values_list('slug', flat=True))
    else:
        tags = set()
    _sync_index(post.id, tags)


def remove_post(post_id):
    _sync_index(post_id, set())


def rebuild_index():
    for post in Post.published.prefetch_related('tags'):
        _sync_index(post.id, {tag.slug for tag in post.tags.all()})


# ------------------------------------------------------------ 兴趣画像
def record_read(visitor_id, post_id):
    """记录一次阅读：更新兴趣画像和已读集合，并让旧的推荐结果失效。"""
    r = get_redis()
    tags = r.smembers(K.post_tags(post_id))   # 直接从 Redis 取标签，不查数据库
    interests = K.visitor_interests(visitor_id)
    read = K.visitor_read(visitor_id)
    pipe = r.pipeline()
    for slug in tags:
        pipe.zincrby(interests, 1, slug)
    pipe.sadd(read, post_id)
    pipe.expire(interests, PROFILE_TTL)
    pipe.expire(read, PROFILE_TTL)
    pipe.delete(K.recommend_result(visitor_id))
    pipe.execute()


def top_interests(visitor_id, count=TOP_TAGS):
    return get_redis().zrevrange(
        K.visitor_interests(visitor_id), 0, count - 1, withscores=True
    )


# ------------------------------------------------------------ 推荐
def _compute(r, visitor_id):
    """用兴趣最高的标签计算推荐结果，写入 blog:recommend:{vid}。"""
    result = K.recommend_result(visitor_id)
    tags = top_interests(visitor_id)
    if not tags:
        return
    pipe = r.pipeline()
    # 加权并集：一篇文章的分 = 它所属的每个标签的兴趣分之和
    # （SET 作为 ZUNIONSTORE 的输入时，每个元素的 score 视为 1）
    pipe.zunionstore(result, {K.tag_posts(slug): score for slug, score in tags})
    # 差集：去掉读过的文章（ZDIFFSTORE 也接受普通 SET 作为输入）
    pipe.zdiffstore(result, [result, K.visitor_read(visitor_id)])
    pipe.expire(result, RESULT_TTL)
    pipe.execute()


def recommend_ids(visitor_id, count=5):
    r = get_redis()
    result = K.recommend_result(visitor_id)
    if not r.exists(result):
        _compute(r, visitor_id)
    ids = [int(m) for m in r.zrevrange(result, 0, count - 1)]

    if len(ids) < count:
        # 冷启动 / 兴趣标签下的文章都读完了：用总榜补齐
        candidates = [
            post_id for post_id, _ in ranking.top_ids('total', count * 3)
            if post_id not in ids
        ]
        if candidates:
            already_read = r.smismember(K.visitor_read(visitor_id), candidates)
            ids += [
                post_id for post_id, seen in zip(candidates, already_read) if not seen
            ][: count - len(ids)]
    return ids


def recommend_posts(visitor_id, count=5):
    ids = recommend_ids(visitor_id, count)
    posts = Post.published.in_bulk(ids)
    return [posts[i] for i in ids if i in posts]
