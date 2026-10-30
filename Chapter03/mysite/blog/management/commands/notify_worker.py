import os
import socket

from django.core.management.base import BaseCommand

from blog.services import notifications


class Command(BaseCommand):
    help = '消费评论事件 Stream，给作者发送站内信（常驻进程）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--consumer',
            default=f'{socket.gethostname()}-{os.getpid()}',
            help='消费者名称，同一消费组内要唯一',
        )
        parser.add_argument('--once', action='store_true', help='只处理一批就退出')

    def handle(self, *args, consumer, once, **options):
        notifications.ensure_group()
        self.stdout.write(f'notify_worker started as "{consumer}"')
        try:
            while True:
                handled = notifications.process_batch(consumer)
                if handled:
                    self.stdout.write(f'handled {handled} event(s)')
                if once:
                    break
        except KeyboardInterrupt:
            self.stdout.write('bye')
