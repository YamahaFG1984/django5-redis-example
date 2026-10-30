from blog import redis_keys as K
from blog.models import Post
from blog.services import ranking, recommend

from .base import RedisTestCase, make_post

VISITOR = 'u:42'


class TagIndexTests(RedisTestCase):
    def test_index_follows_tags_and_status(self):
        post = make_post('Indexed', tags=['redis', 'django'])
        self.assertTrue(self.redis.sismember(K.tag_posts('redis'), post.id))
        self.assertEqual(self.redis.smembers(K.post_tags(post.id)), {'redis', 'django'})

        post.tags.set(['python'])          # m2m_changed
        self.assertFalse(self.redis.sismember(K.tag_posts('redis'), post.id))
        self.assertTrue(self.redis.sismember(K.tag_posts('python'), post.id))

        post.status = Post.Status.DRAFT    # 下线
        post.save()
        self.assertFalse(self.redis.exists(K.tag_posts('python')))

    def test_delete_and_rebuild(self):
        post = make_post('Indexed', tags=['redis'])
        post_id = post.id
        post.delete()
        self.assertFalse(self.redis.exists(K.post_tags(post_id)))
        other = make_post('Other', tags=['redis'])
        self.redis.flushdb()
        recommend.rebuild_index()
        self.assertEqual(self.redis.smembers(K.tag_posts('redis')), {str(other.id)})


class RecommendTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.r1 = make_post('Redis one', tags=['redis'])
        self.r2 = make_post('Redis and Django', tags=['redis', 'django'])
        self.d1 = make_post('Django only', tags=['django'])
        self.p1 = make_post('Python only', tags=['python'])

    def test_record_read_builds_profile(self):
        recommend.record_read(VISITOR, self.r2.id)
        recommend.record_read(VISITOR, self.r1.id)
        self.assertEqual(
            recommend.top_interests(VISITOR), [('redis', 2.0), ('django', 1.0)]
        )
        ttl = self.redis.ttl(K.visitor_interests(VISITOR))
        self.assertTrue(0 < ttl <= recommend.PROFILE_TTL)

    def test_weighted_union_excludes_read_posts(self):
        recommend.record_read(VISITOR, self.r1.id)   # redis +1
        recommend.record_read(VISITOR, self.r1.id)   # redis +1（同一篇再读）
        recommend.record_read(VISITOR, self.d1.id)   # django +1
        # r2 = redis(2) + django(1) = 3，r1 和 d1 已读，p1 不相关
        self.assertEqual(recommend.recommend_ids(VISITOR, count=1), [self.r2.id])
        scores = self.redis.zrange(K.recommend_result(VISITOR), 0, -1, withscores=True)
        self.assertEqual(scores, [(str(self.r2.id), 3.0)])

    def test_cold_start_uses_hot_ranking(self):
        ranking.record_view(self.p1.id, amount=10)
        ranking.record_view(self.d1.id, amount=5)
        self.assertEqual(recommend.recommend_ids('s:new', count=2), [self.p1.id, self.d1.id])

    def test_fill_with_ranking_skips_read_posts(self):
        recommend.record_read(VISITOR, self.r1.id)
        ranking.record_view(self.r1.id, amount=100)  # 最热但已读
        ranking.record_view(self.p1.id, amount=1)
        ids = recommend.recommend_ids(VISITOR, count=3)
        self.assertEqual(ids, [self.r2.id, self.p1.id])

    def test_result_cached_and_invalidated_on_read(self):
        recommend.record_read(VISITOR, self.r1.id)
        recommend.recommend_ids(VISITOR)
        ttl = self.redis.ttl(K.recommend_result(VISITOR))
        self.assertTrue(0 < ttl <= recommend.RESULT_TTL)
        recommend.record_read(VISITOR, self.r2.id)
        self.assertFalse(self.redis.exists(K.recommend_result(VISITOR)))


class RecommendViewTests(RedisTestCase):
    def test_sidebar_recommends_after_reading(self):
        read = make_post('Redis one', tags=['redis'])
        make_post('Redis two', tags=['redis'])
        response = self.client.get(read.get_absolute_url())
        sidebar = response.content.decode().split('Recommended for you')[1].split('<h3>')[0]
        self.assertIn('Redis two', sidebar)
        self.assertNotIn('Redis one', sidebar)
