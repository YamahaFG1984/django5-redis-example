from blog import redis_keys as K
from blog.models import Post
from blog.services import pageviews

from .base import RedisTestCase, make_post


class PageViewServiceTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.post = make_post()

    def test_first_view_counts(self):
        self.assertTrue(pageviews.record_view(self.post, 'u:1'))
        self.assertEqual(pageviews.get_views(self.post), 1)

    def test_dedup_within_window(self):
        pageviews.record_view(self.post, 'u:1')
        self.assertFalse(pageviews.record_view(self.post, 'u:1'))
        self.assertEqual(pageviews.get_views(self.post), 1)
        ttl = self.redis.ttl(K.post_seen(self.post.id, 'u:1'))
        self.assertTrue(0 < ttl <= pageviews.DEDUP_SECONDS)

    def test_dedup_expired_counts_again(self):
        pageviews.record_view(self.post, 'u:1')
        # 模拟 30 分钟过去：删掉防刷标记
        self.redis.delete(K.post_seen(self.post.id, 'u:1'))
        self.assertTrue(pageviews.record_view(self.post, 'u:1'))
        self.assertEqual(pageviews.get_views(self.post), 2)
        self.assertEqual(pageviews.get_uv(self.post), 1)

    def test_unique_visitors(self):
        for visitor in ['u:1', 'u:2', 's:abc', 'u:1']:
            self.redis.delete(K.post_seen(self.post.id, visitor))
            pageviews.record_view(self.post, visitor)
        self.assertEqual(pageviews.get_views(self.post), 4)
        self.assertEqual(pageviews.get_uv(self.post), 3)

    def test_counter_starts_from_db_value(self):
        # Redis 数据丢失后，计数从数据库保存的值继续累加
        self.post.views = 100
        pageviews.record_view(self.post, 'u:1')
        self.assertEqual(pageviews.get_views(self.post), 101)

    def test_get_views_falls_back_to_db(self):
        self.post.views = 7
        self.assertEqual(pageviews.get_views(self.post), 7)

    def test_attach_view_counts_uses_one_mget(self):
        other = make_post('Another one')
        pageviews.record_view(self.post, 'u:1')
        posts = pageviews.attach_view_counts([self.post, other])
        self.assertEqual([p.view_count for p in posts], [1, 0])

    def test_sync_views_to_db(self):
        pageviews.record_view(self.post, 'u:1')
        pageviews.record_view(self.post, 'u:2')
        self.assertEqual(pageviews.sync_views_to_db(), 1)
        self.post.refresh_from_db()
        self.assertEqual(self.post.views, 2)
        self.assertEqual(self.redis.scard(K.post_views_dirty()), 0)
        # 没有新浏览时，什么也不做
        self.assertEqual(pageviews.sync_views_to_db(), 0)


class PageViewViewTests(RedisTestCase):
    def test_detail_counts_once_per_visitor(self):
        post = make_post()
        url = post.get_absolute_url()
        self.client.get(url)
        response = self.client.get(url)
        self.assertContains(response, '1 view')
        self.assertContains(response, '1 reader')

    def test_list_shows_view_counts(self):
        post = make_post()
        self.client.get(post.get_absolute_url())
        response = self.client.get('/blog/')
        self.assertContains(response, '1 view')
        self.assertEqual(Post.objects.get().views, 0)
