from datetime import date, timedelta

from blog import redis_keys as K
from blog.services import checkin

from .base import RedisTestCase, make_user

OCT = date(2026, 10, 1)


def d(day, month=10):
    return date(2026, month, day)


class CheckinServiceTests(RedisTestCase):
    def test_only_once_per_day(self):
        self.assertEqual(checkin.check_in(1, d(5)), {'streak': 1, 'points': 1})
        self.assertIsNone(checkin.check_in(1, d(5)))
        self.assertEqual(checkin.get_stats(1, d(5))['total_days'], 1)

    def test_bit_layout_and_calendar(self):
        for day in (1, 2, 5):
            checkin.check_in(1, d(day))
        # 第 N 天对应 offset N-1
        self.assertEqual(self.redis.getbit(K.checkin_month(1, OCT), 0), 1)
        self.assertEqual(self.redis.getbit(K.checkin_month(1, OCT), 2), 0)
        self.assertEqual(self.redis.getbit(K.checkin_month(1, OCT), 4), 1)
        days = checkin.month_calendar(1, d(5))
        self.assertEqual(len(days), 31)
        self.assertEqual([i for i, on in enumerate(days, 1) if on], [1, 2, 5])
        self.assertEqual(checkin.month_count(1, d(5)), 3)
        # 最大只用到 offset 4，所以只占 1 字节；一整月最多 4 字节
        self.assertEqual(self.redis.strlen(K.checkin_month(1, OCT)), 1)

    def test_streak_and_break(self):
        for day in (1, 2, 3):
            result = checkin.check_in(1, d(day))
        self.assertEqual(result['streak'], 3)
        self.assertEqual(checkin.check_in(1, d(5))['streak'], 1)
        self.assertEqual(checkin.streak_in_month(1, d(5)), 1)
        self.assertEqual(checkin.streak_in_month(1, d(3)), 3)

    def test_streak_across_months(self):
        checkin.check_in(1, d(30))
        checkin.check_in(1, d(31))
        self.assertEqual(checkin.check_in(1, d(1, month=11))['streak'], 3)
        # Bitmap 只能看到本月：11 月只有 1 天
        self.assertEqual(checkin.streak_in_month(1, d(1, month=11)), 1)

    def test_bonus_points_every_7_days(self):
        for day in range(1, 8):
            result = checkin.check_in(1, d(day))
        self.assertEqual(result, {'streak': 7, 'points': 1 + checkin.STREAK_BONUS})
        self.assertEqual(checkin.get_stats(1, d(7))['points'], 7 + checkin.STREAK_BONUS)

    def test_streak_expires_when_missing_a_day(self):
        checkin.check_in(1, d(1))
        self.assertEqual(checkin.get_stats(1, d(2))['streak'], 1)
        self.assertEqual(checkin.get_stats(1, d(3))['streak'], 0)

    def test_global_daily_and_full_week(self):
        for day in range(1, 8):
            checkin.check_in(1, d(day))   # 7 天全勤
        checkin.check_in(2, d(7))         # 只签了一天
        self.assertEqual(checkin.checked_in_count(d(7)), 2)
        self.assertEqual(checkin.full_week_count(d(7)), 1)
        self.assertTrue(0 < self.redis.ttl(K.checkin_full_week(d(7))) <= 60)


class CheckinViewTests(RedisTestCase):
    def test_login_required(self):
        response = self.client.get('/blog/checkin/')
        self.assertEqual(response.status_code, 302)

    def test_check_in_flow(self):
        user = make_user('reader')
        self.client.force_login(user)
        response = self.client.post('/blog/checkin/', follow=True)
        self.assertContains(response, 'Checked in! 1 day streak')
        self.assertContains(response, 'Checked in today')
        response = self.client.post('/blog/checkin/', follow=True)
        self.assertContains(response, 'already checked in')
        self.assertContains(response, '1 reader checked in today')
