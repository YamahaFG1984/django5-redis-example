from unittest import mock

from blog import redis_keys as K
from blog.models import Comment
from blog.services import notifications

from .base import RedisTestCase, make_post, make_user


class NotificationTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.author = make_user('alice')
        self.post = make_post('Alice post', author=self.author)
        notifications.ensure_group()

    def comment(self, body='Nice post'):
        # on_commit 回调在 TestCase 的事务里不会自动执行，这里手动触发
        with self.captureOnCommitCallbacks(execute=True):
            return Comment.objects.create(
                post=self.post, name='Bob', email='bob@example.com', body=body
            )

    def test_comment_publishes_event_after_commit(self):
        self.comment()
        self.assertEqual(self.redis.xlen(K.stream_comments()), 1)

    def test_worker_delivers_and_acks(self):
        self.comment()
        self.assertEqual(notifications.process_batch('w1', block_ms=10), 1)
        self.assertEqual(notifications.unread_count(self.author.id), 1)
        message = notifications.inbox(self.author.id)[0]
        self.assertEqual(message['post_title'], 'Alice post')
        self.assertEqual(message['name'], 'Bob')
        self.assertEqual(notifications.stream_stats(), {'length': 1, 'pending': 0})
        # 读过之后未读数清零
        self.assertEqual(notifications.unread_count(self.author.id), 0)

    def test_nothing_to_do(self):
        self.assertEqual(notifications.process_batch('w1', block_ms=10), 0)

    def test_crashed_consumer_messages_are_reclaimed(self):
        self.comment()
        # 消费者 w1 读到了消息，但在 ACK 之前崩溃
        self.redis.xreadgroup(notifications.GROUP, 'w1', {K.stream_comments(): '>'})
        self.assertEqual(notifications.stream_stats()['pending'], 1)
        # w2 读新消息：什么也没有（那条已经投递给 w1 了）
        self.assertEqual(notifications.process_batch('w2', block_ms=10), 0)
        # 超过空闲时间后，w2 接管并处理
        with mock.patch.object(notifications, 'CLAIM_IDLE_MS', 0):
            self.assertEqual(notifications.process_batch('w2', block_ms=10), 1)
        self.assertEqual(notifications.stream_stats()['pending'], 0)
        self.assertEqual(notifications.unread_count(self.author.id), 1)

    def test_deleted_comment_is_skipped(self):
        comment = self.comment()
        comment.delete()
        self.assertEqual(notifications.process_batch('w1', block_ms=10), 1)
        self.assertEqual(notifications.unread_count(self.author.id), 0)

    def test_inbox_is_capped(self):
        with mock.patch.object(notifications, 'INBOX_SIZE', 3):
            for i in range(5):
                self.comment(f'#{i}')
            notifications.process_batch('w1', block_ms=10)
        self.assertEqual(self.redis.llen(K.user_inbox(self.author.id)), 3)
        self.assertEqual(notifications.unread_count(self.author.id), 5)
        self.assertEqual(notifications.inbox(self.author.id)[0]['excerpt'], '#4')

    def test_ensure_group_is_idempotent(self):
        notifications.ensure_group()
        self.assertEqual(len(self.redis.xinfo_groups(K.stream_comments())), 1)


class NotificationViewTests(RedisTestCase):
    def test_comment_to_inbox_end_to_end(self):
        author = make_user('alice')
        post = make_post('Alice post', author=author)
        notifications.ensure_group()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f'/blog/{post.id}/comment/',
                {'name': 'Bob', 'email': 'b@example.com', 'body': 'Hello Alice'},
            )
        notifications.process_batch('w1', block_ms=10)

        self.client.force_login(author)
        self.assertContains(self.client.get('/blog/'), 'Notifications (1)')
        page = self.client.get('/blog/notifications/')
        self.assertContains(page, 'Hello Alice')
        self.assertNotContains(self.client.get('/blog/'), 'Notifications (1)')
