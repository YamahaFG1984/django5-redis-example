import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from blog import redis_keys as K
from blog.models import Post
from blog.redis_client import get_redis
from blog.services import ranking


class Command(BaseCommand):
    help = '为最近 N 天生成随机浏览数据，方便观察排行榜（只用于演示）'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--seed', type=int, default=42)

    def handle(self, *args, days, seed, **options):
        rng = random.Random(seed)
        r = get_redis()
        today = timezone.localdate()
        posts = list(Post.published.all())
        total = 0
        for offset in range(days):
            day = today - timedelta(days=offset)
            for post in posts:
                # 越新的文章越热，再加一点随机
                age = (today - post.publish.date()).days + 1
                amount = rng.randint(0, 40) // max(1, age // 7)
                if not amount:
                    continue
                ranking.record_view(post.id, day=day, amount=amount)
                pipe = r.pipeline()
                pipe.set(K.post_views(post.id), post.views, nx=True)
                pipe.incrby(K.post_views(post.id), amount)
                pipe.sadd(K.post_views_dirty(), post.id)
                pipe.execute()
                total += amount
        self.stdout.write(self.style.SUCCESS(
            f'Simulated {total} views over {days} day(s) for {len(posts)} posts.'
        ))
