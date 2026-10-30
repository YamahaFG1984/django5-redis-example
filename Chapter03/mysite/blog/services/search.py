"""
搜索增强（step-11）

  ZSET  blog:search:hot                 热搜词，ZINCRBY 计数
  LIST  blog:search:history:{vid}       最近搜索：LREM 去重 + LPUSH + LTRIM 保留 10 条
  ZSET  blog:search:suggest             标题联想：score 全为 0，用 ZRANGEBYLEX 做前缀匹配
"""
from .. import redis_keys as K
from ..models import Post
from ..redis_client import get_redis

HISTORY_SIZE = 10
HISTORY_TTL = 30 * 24 * 3600
SUGGEST_LIMIT = 8
SEP = '|'
# 最大的 Unicode 字符，作为前缀范围的上界：所有以 prefix 开头的字符串都 <= prefix + MAX_CHAR
MAX_CHAR = chr(0x10FFFF)


def normalize(text):
    """统一大小写和空白，让 "Redis"、" redis " 算作同一个词。"""
    return ' '.join(text.lower().split())[:50]


# ------------------------------------------------------------ 热搜与历史
def record_search(visitor_id, query):
    q = normalize(query)
    if not q:
        return
    history = K.search_history(visitor_id)
    pipe = get_redis().pipeline()
    pipe.zincrby(K.search_hot(), 1, q)
    pipe.lrem(history, 0, q)              # 先删掉旧的同名记录（去重）
    pipe.lpush(history, q)                # 插到最前面
    pipe.ltrim(history, 0, HISTORY_SIZE - 1)  # 只保留最近 10 条
    pipe.expire(history, HISTORY_TTL)
    pipe.execute()


def hot_searches(count=10):
    return [
        (q, int(score))
        for q, score in get_redis().zrevrange(K.search_hot(), 0, count - 1, withscores=True)
    ]


def search_history(visitor_id):
    return get_redis().lrange(K.search_history(visitor_id), 0, -1)


def clear_history(visitor_id):
    get_redis().delete(K.search_history(visitor_id))


# ------------------------------------------------------------ 标题联想
def _member(post):
    return f'{normalize(post.title)}{SEP}{post.id}'


def index_title(post, old=None):
    """文章保存时维护联想索引。old 是修改前的文章（标题可能变了）。"""
    pipe = get_redis().pipeline()
    if old is not None:
        pipe.zrem(K.search_suggest(), _member(old))
    if post.status == Post.Status.PUBLISHED:
        pipe.zadd(K.search_suggest(), {_member(post): 0})
    else:
        pipe.zrem(K.search_suggest(), _member(post))
    pipe.execute()


def remove_title(post):
    get_redis().zrem(K.search_suggest(), _member(post))


def rebuild_suggest_index():
    r = get_redis()
    pipe = r.pipeline()
    pipe.delete(K.search_suggest())
    members = {_member(post): 0 for post in Post.published.only('id', 'title')}
    if members:
        pipe.zadd(K.search_suggest(), members)
    pipe.execute()


def suggest(prefix, limit=SUGGEST_LIMIT):
    """返回标题以 prefix 开头的已发布文章。"""
    p = normalize(prefix)
    if not p:
        return []
    # 所有 score 相同时，ZSET 按 member 的字节序排列，[ 表示闭区间
    members = get_redis().zrangebylex(
        K.search_suggest(), f'[{p}', f'[{p}{MAX_CHAR}', start=0, num=limit
    )
    ids = [int(m.rsplit(SEP, 1)[1]) for m in members]
    posts = Post.published.in_bulk(ids)
    return [posts[i] for i in ids if i in posts]
