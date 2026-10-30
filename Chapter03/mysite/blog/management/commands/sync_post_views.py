from django.core.management.base import BaseCommand

from blog.services.pageviews import sync_views_to_db


class Command(BaseCommand):
    help = '把 Redis 中的文章浏览量回写到数据库（建议用 cron 每 5 分钟执行一次）'

    def handle(self, *args, **options):
        updated = sync_views_to_db()
        self.stdout.write(self.style.SUCCESS(f'Synced views for {updated} post(s).'))
