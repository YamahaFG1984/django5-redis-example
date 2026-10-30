from django.test import override_settings

from blog import redis_keys as K
from blog.redis_client import get_redis

from .base import TEST_REDIS_URL, RedisTestCase


class RedisSetupTests(RedisTestCase):
    def test_uses_test_database(self):
        kwargs = get_redis().connection_pool.connection_kwargs
        self.assertEqual(kwargs['db'], 15)
        self.assertTrue(TEST_REDIS_URL.endswith('/15'))

    def test_ping_and_decode_responses(self):
        r = get_redis()
        self.assertTrue(r.ping())
        r.set('hello', 'redis')
        # decode_responses=True，返回 str
        self.assertEqual(r.get('hello'), 'redis')

    def test_get_redis_shares_one_pool(self):
        self.assertIs(get_redis().connection_pool, get_redis().connection_pool)

    def test_key_prefix(self):
        self.assertEqual(K._k('post', 1, 'views'), 'blog:post:1:views')
        with override_settings(REDIS_KEY_PREFIX='demo'):
            self.assertEqual(K._k('post', 1), 'demo:post:1')


class AuthPagesTests(RedisTestCase):
    def test_login_page_renders(self):
        response = self.client.get('/accounts/login/')
        self.assertContains(response, 'Log in')

    def test_sidebar_shows_login_link(self):
        response = self.client.get('/blog/')
        self.assertContains(response, '/accounts/login/?next=/blog/')
