import threading
import time

from django.core.cache import cache

from blog import redis_keys as K
from blog.models import Comment, Post
from blog.services import cache as cache_service
from blog.services.cache import MISSING, RedisLock, get_or_load

from .base import RedisTestCase, make_post


class CacheAsideTests(RedisTestCase):
    def test_loader_called_once(self):
        calls = []

        def loader():
            calls.append(1)
            return {'title': 'Hello'}

        self.assertEqual(get_or_load('k', loader), {'title': 'Hello'})
        self.assertEqual(get_or_load('k', loader), {'title': 'Hello'})
        self.assertEqual(len(calls), 1)

    def test_missing_value_is_cached(self):
        """缓存穿透：不存在的数据也缓存一个空值标记"""
        calls = []

        def loader():
            calls.append(1)
            return None

        self.assertIsNone(get_or_load('k', loader))
        self.assertIsNone(get_or_load('k', loader))
        self.assertEqual(len(calls), 1)
        self.assertEqual(cache.get('k'), MISSING)

    def test_only_one_loader_under_concurrency(self):
        """缓存击穿：10 个线程同时未命中，只有 1 个去查数据库"""
        calls = []

        def slow_loader():
            calls.append(1)
            time.sleep(0.2)
            return 'value'

        results = []
        threads = [
            threading.Thread(target=lambda: results.append(get_or_load('hot', slow_loader)))
            for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results, ['value'] * 10)
        self.assertEqual(len(calls), 1)

    def test_falls_back_to_loader_when_lock_holder_is_stuck(self):
        RedisLock('cache:k').acquire()   # 模拟另一个请求拿着锁一直不放
        value = get_or_load('k', lambda: 'from-db', lock_wait=0.1)
        self.assertEqual(value, 'from-db')
        self.assertIsNone(cache.get('k'))

    def test_jitter_range(self):
        for _ in range(100):
            self.assertTrue(300 <= cache_service.jitter(300) <= 360)


class RedisLockTests(RedisTestCase):
    def test_lock_is_exclusive_and_expires(self):
        first, second = RedisLock('job'), RedisLock('job')
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        self.assertTrue(0 < self.redis.pttl(K.lock('job')) <= 10_000)

    def test_only_owner_can_release(self):
        first, second = RedisLock('job'), RedisLock('job')
        first.acquire()
        self.assertFalse(second.release())
        self.assertTrue(self.redis.exists(K.lock('job')))
        self.assertTrue(first.release())
        self.assertFalse(self.redis.exists(K.lock('job')))


class PostDetailCacheTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.post = make_post('Cached post')

    def test_detail_is_served_from_cache_and_invalidated_on_save(self):
        url = self.post.get_absolute_url()
        self.client.get(url)
        # 绕过信号直接改数据库：缓存还在，页面显示旧标题
        Post.objects.filter(id=self.post.id).update(title='Changed quietly')
        self.assertContains(self.client.get(url), 'Cached post')
        # 通过 save() 修改：信号删除缓存，页面显示新标题
        self.post.title = 'Changed properly'
        self.post.save()
        self.assertContains(self.client.get(url), 'Changed properly')

    def test_slug_change_invalidates_old_url(self):
        old_url = self.post.get_absolute_url()
        self.client.get(old_url)
        self.post.slug = 'new-slug'
        self.post.save()
        self.assertEqual(self.client.get(old_url).status_code, 404)

    def test_unknown_post_is_404_and_cached(self):
        response = self.client.get('/blog/2020/1/1/nope/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(cache.get(K.cache_post_detail(2020, 1, 1, 'nope')), MISSING)

    def test_unpublish_hides_cached_post(self):
        url = self.post.get_absolute_url()
        self.client.get(url)
        self.post.status = Post.Status.DRAFT
        self.post.save()
        self.assertEqual(self.client.get(url).status_code, 404)


class SidebarCacheTests(RedisTestCase):
    def test_sidebar_namespace_bumped_on_comment(self):
        post = make_post()
        self.client.get('/blog/')
        ns = cache.get(K.cache_sidebar_ns())
        self.assertIsNotNone(cache.get(K.cache_sidebar(ns, 'total_posts')))
        Comment.objects.create(post=post, name='a', email='a@a.com', body='hi')
        self.assertEqual(cache.get(K.cache_sidebar_ns()), ns + 1)

    def test_new_post_shows_up_in_sidebar(self):
        make_post('First')
        self.assertContains(self.client.get('/blog/'), "written 1 posts")
        make_post('Second')
        self.assertContains(self.client.get('/blog/'), "written 2 posts")
