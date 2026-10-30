"""
每日签到（step-07）

  BITMAP  blog:checkin:{uid}:{yyyymm}    个人月历：第 N 天签到 → 第 N-1 位置 1（一个月最多 4 字节）
  BITMAP  blog:checkin:day:{yyyymmdd}     全站日签到：用户 ID 对应的位置 1
  HASH    blog:user:{uid}:checkin         累计天数、连续天数、最后签到日期、积分
"""
import calendar
from datetime import timedelta

from django.utils import timezone

from .. import redis_keys as K
from ..redis_client import get_redis

MONTH_TTL = 400 * 24 * 3600
DAILY_TTL = 40 * 24 * 3600
POINTS_PER_DAY = 1
STREAK_BONUS_EVERY = 7   # 每连续签到 7 天
STREAK_BONUS = 5         # 额外奖励 5 分


def check_in(user_id, day=None):
    """
    签到。今天已经签过返回 None；否则返回 {'streak': 连续天数, 'points': 本次获得积分}。
    """
    day = day or timezone.localdate()
    r = get_redis()
    month_key = K.checkin_month(user_id, day)
    daily_key = K.checkin_daily(day)

    pipe = r.pipeline()
    # SETBIT 返回这一位原来的值：0 表示今天第一次签到
    pipe.setbit(month_key, day.day - 1, 1)
    pipe.expire(month_key, MONTH_TTL)
    pipe.setbit(daily_key, user_id, 1)
    pipe.expire(daily_key, DAILY_TTL)
    already_checked_in = pipe.execute()[0]
    if already_checked_in:
        return None
    # 同一用户同一天只有一个请求能走到这里，所以下面的读-改-写不会有并发问题
    return _update_stats(r, user_id, day)


def _update_stats(r, user_id, day):
    key = K.user_checkin_stats(user_id)
    stats = r.hgetall(key)
    yesterday = (day - timedelta(days=1)).isoformat()
    if stats.get('last_date') == yesterday:
        streak = int(stats['streak']) + 1   # 昨天签过：连续天数 +1（跨月也成立）
    else:
        streak = 1                          # 断签了，从 1 重新开始
    points = POINTS_PER_DAY
    if streak % STREAK_BONUS_EVERY == 0:
        points += STREAK_BONUS

    pipe = r.pipeline()
    pipe.hset(key, mapping={'last_date': day.isoformat(), 'streak': streak})
    pipe.hincrby(key, 'total_days', 1)
    pipe.hincrby(key, 'points', points)
    pipe.execute()
    return {'streak': streak, 'points': points}


def get_stats(user_id, day=None):
    day = day or timezone.localdate()
    stats = get_redis().hgetall(K.user_checkin_stats(user_id))
    last_date = stats.get('last_date')
    # 最后一次签到是今天或昨天，连续天数才有效
    alive = last_date in (day.isoformat(), (day - timedelta(days=1)).isoformat())
    return {
        'total_days': int(stats.get('total_days', 0)),
        'streak': int(stats.get('streak', 0)) if alive else 0,
        'points': int(stats.get('points', 0)),
        'checked_in_today': last_date == day.isoformat(),
    }


def month_calendar(user_id, day=None):
    """
    返回本月每一天是否签到：[True, False, ...]，长度 = 本月天数。
    BITFIELD GET u{N} 0 把前 N 位当作一个无符号整数一次读出来。
    """
    day = day or timezone.localdate()
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    value = (
        get_redis().bitfield(K.checkin_month(user_id, day))
        .get(f'u{days_in_month}', 0)
        .execute()[0]
    )
    # offset 0（1 号）是最高位，offset N-1（月底）是最低位
    return [
        bool(value >> (days_in_month - d) & 1) for d in range(1, days_in_month + 1)
    ]


def month_count(user_id, day=None):
    day = day or timezone.localdate()
    return get_redis().bitcount(K.checkin_month(user_id, day))


def streak_in_month(user_id, day=None):
    """
    只用 Bitmap 计算「本月内截止今天」的连续签到天数：
    取出 1 号到今天的位，从最低位（今天）开始数连续的 1。
    """
    day = day or timezone.localdate()
    value = (
        get_redis().bitfield(K.checkin_month(user_id, day))
        .get(f'u{day.day}', 0)
        .execute()[0]
    )
    streak = 0
    while value & 1:
        streak += 1
        value >>= 1
    return streak


def checked_in_count(day=None):
    """某天全站签到人数。"""
    day = day or timezone.localdate()
    return get_redis().bitcount(K.checkin_daily(day))


def full_week_count(day=None):
    """截止 day 连续 7 天每天都签到的人数：7 个日 Bitmap 按位与。"""
    day = day or timezone.localdate()
    r = get_redis()
    dest = K.checkin_full_week(day)
    days = [K.checkin_daily(day - timedelta(days=i)) for i in range(7)]
    pipe = r.pipeline()
    pipe.bitop('AND', dest, *days)
    pipe.expire(dest, 60)
    pipe.bitcount(dest)
    return pipe.execute()[-1]
