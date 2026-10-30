import threading

from blog import redis_keys as K
from blog.services.ratelimit import fixed_window, sliding_window

from .base import RedisTestCase, make_post

T0 = 1_800_000_000  # 一个整分钟的时间戳，方便推算窗口边界


class FixedWindowTests(RedisTestCase):
    def test_limit_and_retry_after(self):
        for i in range(3):
            self.assertTrue(fixed_window('t', 'ip', 3, 60, now=T0 + i).allowed)
        decision = fixed_window('t', 'ip', 3, 60, now=T0 + 10)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.retry_after, 51)
        ttl = self.redis.ttl(K.ratelimit_fixed('t', 'ip', T0 // 60))
        self.assertTrue(0 < ttl <= 60)

    def test_next_window_resets(self):
        for i in range(4):
            fixed_window('t', 'ip', 3, 60, now=T0 + i)
        self.assertTrue(fixed_window('t', 'ip', 3, 60, now=T0 + 60).allowed)

    def test_boundary_burst(self):
        """固定窗口的缺陷：窗口交界处 2 秒内可以通过 2 倍的请求"""
        allowed = [fixed_window('t', 'ip', 3, 60, now=T0 + 59).allowed for _ in range(3)]
        allowed += [fixed_window('t', 'ip', 3, 60, now=T0 + 60).allowed for _ in range(3)]
        self.assertEqual(allowed, [True] * 6)

    def test_atomic_under_concurrency(self):
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(
                fixed_window('t', 'ip', 5, 60, now=T0).allowed))
            for _ in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 5)


class SlidingWindowTests(RedisTestCase):
    def test_limit_and_slide(self):
        for t in (0, 10, 20):
            self.assertTrue(sliding_window('t', 'ip', 3, 60, now=T0 + t).allowed)
        denied = sliding_window('t', 'ip', 3, 60, now=T0 + 30)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.retry_after, 30)   # T0 那次请求 30 秒后滑出窗口
        # 61 秒后，第一条记录已滑出
        self.assertTrue(sliding_window('t', 'ip', 3, 60, now=T0 + 61).allowed)

    def test_no_boundary_burst(self):
        allowed = [sliding_window('t', 'ip', 3, 60, now=T0 + 59).allowed for _ in range(3)]
        allowed += [sliding_window('t', 'ip', 3, 60, now=T0 + 60).allowed for _ in range(3)]
        self.assertEqual(allowed, [True] * 3 + [False] * 3)

    def test_rejected_requests_are_not_logged(self):
        for _ in range(5):
            sliding_window('t', 'ip', 3, 60, now=T0)
        self.assertEqual(self.redis.zcard(K.ratelimit_sliding('t', 'ip')), 3)
        self.assertTrue(0 < self.redis.pttl(K.ratelimit_sliding('t', 'ip')) <= 60_000)


class RateLimitViewTests(RedisTestCase):
    def test_fourth_comment_in_a_minute_is_rejected(self):
        post = make_post()
        url = f'/blog/{post.id}/comment/'
        data = {'name': 'Spammer', 'email': 's@example.com', 'body': 'Buy now'}
        for _ in range(3):
            self.assertEqual(self.client.post(url, data).status_code, 200)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 429)
        self.assertTrue(1 <= int(response['Retry-After']) <= 60)
        self.assertEqual(post.comments.count(), 3)

    def test_share_get_is_not_limited(self):
        post = make_post()
        for _ in range(7):
            self.assertEqual(self.client.get(f'/blog/{post.id}/share/').status_code, 200)
