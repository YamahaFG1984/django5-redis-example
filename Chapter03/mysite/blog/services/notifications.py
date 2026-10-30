"""
评论通知（step-12）

Web 进程只负责把「有新评论」这个事件写进 Stream，立即返回；
后台进程 notify_worker 以消费组的方式读取事件，生成站内信。

  STREAM  blog:stream:comments    XADD 生产 / XREADGROUP 消费 / XACK 确认 / XAUTOCLAIM 接管
  LIST    blog:user:{id}:inbox    站内信，LPUSH + LTRIM 保留 50 条
  STRING  blog:user:{id}:unread   未读数，INCR / SET 0
"""
import json

import redis

from .. import redis_keys as K
from ..models import Comment
from ..redis_client import get_redis

GROUP = 'notifier'
STREAM_MAXLEN = 10_000
INBOX_SIZE = 50
CLAIM_IDLE_MS = 60_000   # 消息被领取 60 秒还没 ACK，就认为那个消费者挂了


# ------------------------------------------------------------ 生产者（Web 进程）
def publish_comment(comment):
    get_redis().xadd(
        K.stream_comments(),
        {'comment_id': comment.id, 'post_id': comment.post_id},
        # 近似截断：只保留最近约 1 万条，避免 Stream 无限增长
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )


# ------------------------------------------------------------ 消费者（后台进程）
def ensure_group():
    """创建消费组（已存在则忽略）。id='0' 表示从 Stream 的第一条消息开始消费。"""
    try:
        get_redis().xgroup_create(K.stream_comments(), GROUP, id='0', mkstream=True)
    except redis.ResponseError as exc:
        if 'BUSYGROUP' not in str(exc):
            raise


def handle_event(fields):
    """处理一条评论事件：给文章作者发一条站内信。"""
    comment = (
        Comment.objects.select_related('post')
        .filter(id=int(fields['comment_id']))
        .first()
    )
    if comment is None:
        return False   # 评论已经被删除，直接丢弃
    post = comment.post
    message = json.dumps({
        'post_title': post.title,
        'url': post.get_absolute_url(),
        'name': comment.name,
        'excerpt': comment.body[:80],
        'created': comment.created.isoformat(),
    })
    pipe = get_redis().pipeline()
    pipe.lpush(K.user_inbox(post.author_id), message)
    pipe.ltrim(K.user_inbox(post.author_id), 0, INBOX_SIZE - 1)
    pipe.incr(K.user_unread(post.author_id))
    pipe.execute()
    return True


def process_batch(consumer, count=10, block_ms=5000):
    """处理一批消息，返回处理的条数。"""
    r = get_redis()
    stream = K.stream_comments()
    # 1. 先接管其他消费者领取后长时间没有 ACK 的消息（消费者崩溃了）
    _, messages, _ = r.xautoclaim(
        stream, GROUP, consumer, min_idle_time=CLAIM_IDLE_MS, start_id='0-0', count=count
    )
    # 2. 没有要接管的，就读取新消息：">" 表示从未投递给本组任何消费者的消息
    if not messages:
        response = r.xreadgroup(GROUP, consumer, {stream: '>'}, count=count, block=block_ms)
        messages = response[0][1] if response else []

    for message_id, fields in messages:
        if fields:
            handle_event(fields)
        # 3. 处理完才 ACK；ACK 之前崩溃的话，消息还在待处理列表（PEL）中，会被重新处理
        r.xack(stream, GROUP, message_id)
    return len(messages)


def stream_stats():
    r = get_redis()
    stream = K.stream_comments()
    if not r.exists(stream):
        return {'length': 0, 'pending': 0}
    pending = r.xpending(stream, GROUP)['pending'] if _group_exists(r, stream) else 0
    return {'length': r.xlen(stream), 'pending': pending}


def _group_exists(r, stream):
    return any(group['name'] == GROUP for group in r.xinfo_groups(stream))


# ------------------------------------------------------------ 站内信
def unread_count(user_id):
    return int(get_redis().get(K.user_unread(user_id)) or 0)


def inbox(user_id, mark_read=True):
    r = get_redis()
    messages = [json.loads(m) for m in r.lrange(K.user_inbox(user_id), 0, -1)]
    if mark_read:
        r.set(K.user_unread(user_id), 0)
    return messages
