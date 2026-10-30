from django.core.management.base import BaseCommand

from blog.services import timeline


class Command(BaseCommand):
    help = '从数据库重建 Redis 中可以推导出来的索引数据'

    def handle(self, *args, **options):
        timeline.rebuild_outboxes()
        self.stdout.write('  step-08 author outboxes rebuilt')
        self.stdout.write(self.style.SUCCESS('Done.'))
