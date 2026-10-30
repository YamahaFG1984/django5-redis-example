from blog import redis_keys as K
from blog.services import likes

from .base import RedisTestCase, make_post, make_user


class LikeServiceTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.a = make_post('Post A')
        self.b = make_post('Post B')

    def test_like_is_idempotent(self):
        self.assertTrue(likes.like(1, self.a.id))
        self.assertFalse(likes.like(1, self.a.id))
        self.assertEqual(likes.like_count(self.a.id), 1)
        self.assertTrue(likes.has_liked(1, self.a.id))

    def test_unlike(self):
        likes.like(1, self.a.id)
        self.assertTrue(likes.unlike(1, self.a.id))
        self.assertFalse(likes.unlike(1, self.a.id))
        self.assertEqual(likes.like_count(self.a.id), 0)
        self.assertEqual(self.redis.zcard(K.user_likes(1)), 0)

    def test_liked_posts_newest_first(self):
        likes.like(1, self.a.id)
        likes.like(1, self.b.id)
        # 重复点赞不会改变时间（ZADD NX）
        likes.like(1, self.a.id)
        self.assertEqual(
            [p.id for p in likes.liked_posts(1)], [self.b.id, self.a.id]
        )

    def test_attach_like_info(self):
        user = make_user('reader')
        likes.like(user.id, self.a.id)
        likes.like(999, self.a.id)
        likes.like(999, self.b.id)
        posts = likes.attach_like_info([self.a, self.b], user)
        self.assertEqual([(p.like_count, p.liked) for p in posts], [(2, True), (1, False)])

    def test_delete_post_cleans_up(self):
        likes.like(1, self.a.id)
        likes.like(2, self.a.id)
        self.a.delete()
        self.assertFalse(self.redis.exists(K.post_likers(self.a.id)))
        self.assertEqual(self.redis.zcard(K.user_likes(1)), 0)


class LikeViewTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.post = make_post()
        self.user = make_user('reader')
        self.url = f'/blog/{self.post.id}/like/'

    def test_login_required(self):
        response = self.client.post(self.url)
        self.assertRedirects(
            response, f'/accounts/login/?next={self.url}', fetch_redirect_response=False
        )

    def test_like_and_unlike(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'action': 'like'})
        self.assertRedirects(response, self.post.get_absolute_url())
        page = self.client.get(self.post.get_absolute_url())
        self.assertContains(page, '1 like')
        self.assertContains(page, 'Liked')

        self.client.post(self.url, {'action': 'unlike'})
        self.assertContains(self.client.get(self.post.get_absolute_url()), '0 likes')

    def test_my_likes_page(self):
        likes.like(self.user.id, self.post.id)
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/blog/likes/'), self.post.title)
