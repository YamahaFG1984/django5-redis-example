from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.test import TestCase, override_settings

from blog.redis_client import get_redis


def _with_db(url, db):
    """把 redis://host:6379/0 换成 redis://host:6379/{db}"""
    return urlunparse(urlparse(url)._replace(path=f'/{db}'))


TEST_REDIS_URL = _with_db(settings.REDIS_URL, 15)


@override_settings(REDIS_URL=TEST_REDIS_URL)
class RedisTestCase(TestCase):
    """
    连接真实 Redis 的测试基类。

    使用 db15，避免误删开发数据；每个用例开始前清空，保证用例之间互不影响。
    """

    def setUp(self):
        super().setUp()
        self.redis = get_redis()
        self.redis.flushdb()


def make_user(username='alice'):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username, password='redis123')


def make_post(title='Hello Redis', author=None, tags=(), **fields):
    from django.utils.text import slugify

    from blog.models import Post

    post = Post.objects.create(
        title=title,
        slug=slugify(title),
        author=author or make_user(f'author-{slugify(title)}'),
        body='Demo body',
        status=fields.pop('status', Post.Status.PUBLISHED),
        **fields,
    )
    if tags:
        post.tags.set(tags)
    return post
