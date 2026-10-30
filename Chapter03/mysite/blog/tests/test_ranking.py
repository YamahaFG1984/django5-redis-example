from datetime import date, timedelta

from blog import redis_keys as K
from blog.models import Post
from blog.services import ranking

from .base import RedisTestCase, make_post

TODAY = date(2026, 10, 30)


class RankingTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.a = make_post('Post A')
        self.b = make_post('Post B')

    def test_record_view_updates_total_and_daily(self):
        ranking.record_view(self.a.id, day=TODAY)
        ranking.record_view(self.a.id, day=TODAY)
        ranking.record_view(self.b.id, day=TODAY)
        self.assertEqual(
            ranking.top_ids('total'), [(self.a.id, 2), (self.b.id, 1)]
        )
        self.assertEqual(
            ranking.top_ids('day', today=TODAY), [(self.a.id, 2), (self.b.id, 1)]
        )
        ttl = self.redis.ttl(K.rank_daily(TODAY))
        self.assertTrue(0 < ttl <= ranking.DAILY_TTL)

    def test_weekly_union_sums_last_7_days(self):
        ranking.record_view(self.a.id, day=TODAY, amount=3)
        ranking.record_view(self.b.id, day=TODAY - timedelta(days=1), amount=2)
        ranking.record_view(self.b.id, day=TODAY - timedelta(days=6), amount=2)
        # 第 8 天前的数据不算在周榜里
        ranking.record_view(self.a.id, day=TODAY - timedelta(days=7), amount=100)
        self.assertEqual(
            ranking.top_ids('week', today=TODAY), [(self.b.id, 4), (self.a.id, 3)]
        )
        ttl = self.redis.ttl(K.rank_weekly(TODAY))
        self.assertTrue(0 < ttl <= ranking.WEEKLY_CACHE_SECONDS)

    def test_top_posts_skips_unpublished(self):
        ranking.record_view(self.a.id, amount=5)
        ranking.record_view(self.b.id, amount=1)
        Post.objects.filter(id=self.a.id).update(status=Post.Status.DRAFT)
        posts = ranking.top_posts('total')
        self.assertEqual([(p.id, p.score) for p in posts], [(self.b.id, 1)])

    def test_unpublish_signal_removes_post(self):
        ranking.record_view(self.a.id)
        self.a.status = Post.Status.DRAFT
        self.a.save()
        self.assertIsNone(self.redis.zscore(K.rank_total(), self.a.id))

    def test_delete_signal_removes_post(self):
        ranking.record_view(self.a.id)
        self.a.delete()
        self.assertEqual(self.redis.zcard(K.rank_total()), 0)


class RankingViewTests(RedisTestCase):
    def test_detail_view_ranks_once_per_visitor(self):
        post = make_post()
        self.client.get(post.get_absolute_url())
        self.client.get(post.get_absolute_url())
        self.assertEqual(ranking.top_ids('total'), [(post.id, 1)])

    def test_ranking_page_and_sidebar(self):
        post = make_post('Popular post')
        ranking.record_view(post.id, amount=9)
        response = self.client.get('/blog/ranking/')
        # 3 个榜单各一次
        self.assertContains(response, '9 views', count=3)
        # 侧边栏的「本周热门」
        self.assertContains(response, '<span class="score">9</span>', html=True)
