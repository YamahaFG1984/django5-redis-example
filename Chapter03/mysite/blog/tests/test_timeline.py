from datetime import timedelta
from unittest import mock

from django.utils import timezone

from blog import redis_keys as K
from blog.models import Post
from blog.services import timeline

from .base import RedisTestCase, make_post, make_user


def post_by(author, title, minutes_ago):
    return make_post(
        title, author=author, publish=timezone.now() - timedelta(minutes=minutes_ago)
    )


class FollowTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.alice, self.bob, self.carol = (make_user(n) for n in ('alice', 'bob', 'carol'))

    def test_follow_and_unfollow(self):
        self.assertTrue(timeline.follow(self.bob.id, self.alice.id))
        self.assertFalse(timeline.follow(self.bob.id, self.alice.id))
        self.assertTrue(timeline.is_following(self.bob.id, self.alice.id))
        self.assertEqual(timeline.follow_counts(self.alice.id), {'following': 0, 'followers': 1})
        self.assertTrue(timeline.unfollow(self.bob.id, self.alice.id))
        self.assertEqual(timeline.follow_counts(self.alice.id)['followers'], 0)

    def test_cannot_follow_yourself(self):
        with self.assertRaises(ValueError):
            timeline.follow(self.bob.id, self.bob.id)

    def test_common_and_mutual(self):
        timeline.follow(self.bob.id, self.alice.id)
        timeline.follow(self.carol.id, self.alice.id)
        timeline.follow(self.alice.id, self.bob.id)
        self.assertEqual(timeline.common_following(self.bob.id, self.carol.id), [self.alice])
        self.assertEqual(timeline.mutual_follows(self.alice.id), [self.bob])


class TimelineTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.alice, self.bob, self.carol = (make_user(n) for n in ('alice', 'bob', 'carol'))
        timeline.follow(self.bob.id, self.alice.id)

    def ids(self, user, **kwargs):
        posts, _ = timeline.get_timeline(user.id, **kwargs)
        return [p.title for p in posts]

    def test_publish_fans_out_to_followers_only(self):
        post_by(self.alice, 'A1', 10)
        self.assertEqual(self.ids(self.bob), ['A1'])
        self.assertEqual(self.ids(self.carol), [])

    def test_follow_backfills_and_unfollow_removes(self):
        post_by(self.alice, 'A1', 20)
        post_by(self.alice, 'A2', 10)
        timeline.follow(self.carol.id, self.alice.id)
        self.assertEqual(self.ids(self.carol), ['A2', 'A1'])
        timeline.unfollow(self.carol.id, self.alice.id)
        self.assertEqual(self.ids(self.carol), [])

    def test_unpublish_removes_from_timelines(self):
        post = post_by(self.alice, 'A1', 10)
        post.status = Post.Status.DRAFT
        post.save()
        self.assertEqual(self.redis.zcard(K.timeline(self.bob.id)), 0)
        self.assertEqual(self.redis.zcard(K.user_posts(self.alice.id)), 0)

    def test_timeline_is_trimmed(self):
        with mock.patch.object(timeline, 'TIMELINE_MAX', 3):
            for i in range(5):
                post_by(self.alice, f'A{i}', 50 - i)
        self.assertEqual(self.redis.zcard(K.timeline(self.bob.id)), 3)
        self.assertEqual(self.ids(self.bob), ['A4', 'A3', 'A2'])

    def test_cursor_pagination_survives_new_posts(self):
        for i in range(5):
            post_by(self.alice, f'A{i}', 50 - i)
        page1, cursor = timeline.get_timeline(self.bob.id, count=2)
        self.assertEqual([p.title for p in page1], ['A4', 'A3'])
        # 翻页之前，又有一篇新文章发布
        post_by(self.alice, 'NEW', 0)
        page2, cursor = timeline.get_timeline(self.bob.id, before=cursor, count=2)
        self.assertEqual([p.title for p in page2], ['A2', 'A1'])
        page3, cursor = timeline.get_timeline(self.bob.id, before=cursor, count=2)
        self.assertEqual([p.title for p in page3], ['A0'])
        self.assertIsNone(cursor)

    def test_rebuild_outboxes(self):
        post_by(self.alice, 'A1', 10)
        self.redis.flushdb()
        timeline.rebuild_outboxes()
        self.assertEqual(self.redis.zcard(K.user_posts(self.alice.id)), 1)


class TimelineViewTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.alice, self.bob = make_user('alice'), make_user('bob')
        post_by(self.alice, 'Alice writes', 5)
        self.client.force_login(self.bob)

    def test_follow_from_author_page_then_read_timeline(self):
        page = self.client.get('/blog/author/alice/')
        self.assertContains(page, '0 followers')
        self.client.post('/blog/author/alice/follow/', {'action': 'follow'})
        self.assertContains(self.client.get('/blog/author/alice/'), 'Unfollow')
        self.assertContains(self.client.get('/blog/timeline/'), 'Alice writes')

    def test_timeline_page_with_bad_cursor(self):
        response = self.client.get('/blog/timeline/?before=abc')
        self.assertEqual(response.status_code, 200)
