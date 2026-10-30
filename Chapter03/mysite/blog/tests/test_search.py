from blog import redis_keys as K
from blog.models import Post
from blog.services import search

from .base import RedisTestCase, make_post

VISITOR = 's:abc'


class HotAndHistoryTests(RedisTestCase):
    def test_normalize(self):
        self.assertEqual(search.normalize('  Redis   STREAMS '), 'redis streams')

    def test_hot_searches(self):
        for q in ['Redis', 'redis ', 'django', 'REDIS']:
            search.record_search(VISITOR, q)
        self.assertEqual(search.hot_searches(), [('redis', 3), ('django', 1)])

    def test_history_dedup_newest_first_and_capped(self):
        for q in ['a', 'b', 'a']:
            search.record_search(VISITOR, q)
        self.assertEqual(search.search_history(VISITOR), ['a', 'b'])
        for i in range(20):
            search.record_search(VISITOR, f'q{i}')
        history = search.search_history(VISITOR)
        self.assertEqual(len(history), search.HISTORY_SIZE)
        self.assertEqual(history[0], 'q19')
        self.assertTrue(0 < self.redis.ttl(K.search_history(VISITOR)) <= search.HISTORY_TTL)

    def test_blank_query_ignored(self):
        search.record_search(VISITOR, '   ')
        self.assertEqual(self.redis.zcard(K.search_hot()), 0)


class SuggestTests(RedisTestCase):
    def setUp(self):
        super().setUp()
        self.streams = make_post('Redis Streams as a Message Queue')
        self.strings = make_post('Redis Strings and Atomic Counters')
        self.orm = make_post('Django ORM Tips')

    def titles(self, prefix):
        return [p.title for p in search.suggest(prefix)]

    def test_prefix_match_in_lexical_order(self):
        self.assertEqual(
            self.titles('redis str'),
            ['Redis Streams as a Message Queue', 'Redis Strings and Atomic Counters'],
        )
        self.assertEqual(self.titles('REDIS STRI'), ['Redis Strings and Atomic Counters'])
        self.assertEqual(self.titles('dj'), ['Django ORM Tips'])
        self.assertEqual(self.titles('orm'), [])     # 只匹配开头
        self.assertEqual(self.titles(''), [])

    def test_non_ascii_titles(self):
        make_post('Redis 入门指南')
        self.assertEqual(self.titles('redis 入'), ['Redis 入门指南'])

    def test_rename_and_unpublish_update_index(self):
        self.orm.title = 'Async Django'
        self.orm.save()
        self.assertEqual(self.titles('dj'), [])
        self.assertEqual(self.titles('async'), ['Async Django'])
        self.orm.status = Post.Status.DRAFT
        self.orm.save()
        self.assertEqual(self.titles('async'), [])

    def test_delete_and_rebuild(self):
        self.streams.delete()
        self.assertEqual(self.titles('redis str'), ['Redis Strings and Atomic Counters'])
        self.redis.flushdb()
        search.rebuild_suggest_index()
        self.assertEqual(self.redis.zcard(K.search_suggest()), 2)


class SearchViewTests(RedisTestCase):
    def test_search_records_and_shows_history(self):
        make_post('Redis basics')
        self.client.get('/blog/search/', {'query': 'Redis'})
        response = self.client.get('/blog/search/')
        self.assertContains(response, 'Your recent searches')
        self.assertContains(response, '<span class="score">1</span>', html=True)
        self.client.post('/blog/search/history/clear/')
        self.assertNotContains(self.client.get('/blog/search/'), 'Your recent searches')

    def test_suggest_endpoint(self):
        post = make_post('Redis basics')
        response = self.client.get('/blog/search/suggest/', {'q': 'red'})
        self.assertEqual(
            response.json(), [{'title': 'Redis basics', 'url': post.get_absolute_url()}]
        )
