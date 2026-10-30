from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from blog.models import Comment, Post
from blog.services import checkin, timeline

PASSWORD = 'redis123'

# (作者, 标题, 标签, 几天前发布, 是否发布)
POSTS = [
    ('alice', 'Getting Started with Redis', ['redis', 'database'], 30, True),
    ('alice', 'Redis Strings and Atomic Counters', ['redis', 'performance'], 26, True),
    ('bob', 'Django ORM Tips and Tricks', ['django', 'python', 'database'], 24, True),
    ('bob', 'Caching Strategies in Django', ['django', 'cache', 'performance'], 20, True),
    ('alice', 'Sorted Sets for Leaderboards', ['redis', 'performance'], 17, True),
    ('carol', 'Python Generators Explained', ['python'], 15, True),
    ('bob', 'Building a REST API with Django', ['django', 'python'], 12, True),
    ('carol', 'PostgreSQL Full-Text Search', ['database', 'postgresql'], 10, True),
    ('alice', 'Redis Streams as a Message Queue', ['redis', 'queue'], 7, True),
    ('carol', 'Async Views in Django 5', ['django', 'python', 'performance'], 5, True),
    ('bob', 'Rate Limiting with Redis and Lua', ['redis', 'django', 'security'], 3, True),
    ('carol', 'Understanding Bitmaps and HyperLogLog', ['redis', 'database'], 1, True),
    ('alice', 'Redis Cluster Notes', ['redis'], 0, False),
]

BODY = """This is a demo post about **{title}**.

Redis is an in-memory data structure store. Django is a high-level Python
web framework. In this post we look at how *{tag}* fits into a real project.

* Why it matters
* How it works
* Things to watch out for

Happy hacking!
"""

COMMENTS = [
    ('Dave', 'dave@example.com', 'Great introduction, thanks!'),
    ('Erin', 'erin@example.com', 'Could you write more about this topic?'),
]


class Command(BaseCommand):
    help = '创建演示用户、文章和评论（可重复执行）'

    def handle(self, *args, **options):
        User = get_user_model()
        users = {}
        for username in ['alice', 'bob', 'carol']:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'email': f'{username}@example.com'},
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            users[username] = user

        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin123')

        now = timezone.now()
        for author, title, tags, days_ago, published in POSTS:
            post, created = Post.objects.update_or_create(
                slug=slugify(title),
                defaults={
                    'title': title,
                    'author': users[author],
                    'body': BODY.format(title=title, tag=tags[0]),
                    'publish': now - timedelta(days=days_ago, hours=1),
                    'status': (
                        Post.Status.PUBLISHED if published else Post.Status.DRAFT
                    ),
                },
            )
            post.tags.set(tags)
            if created and published:
                for name, email, body in COMMENTS[: days_ago % 3]:
                    Comment.objects.create(
                        post=post, name=name, email=email, body=body
                    )

        # step-08 关注关系：bob 关注 alice；carol 关注 alice 和 bob；alice 关注 carol
        for follower, followee in [
            ('bob', 'alice'), ('carol', 'alice'), ('carol', 'bob'), ('alice', 'carol'),
        ]:
            timeline.follow(users[follower].id, users[followee].id)

        # step-07 alice 在最近 9 天里签到了 8 天（4 天前断签，今天还没签）
        today = timezone.localdate()
        for offset in range(9, 0, -1):
            if offset != 4:
                checkin.check_in(users['alice'].id, today - timedelta(days=offset))

        self.stdout.write(self.style.SUCCESS(
            f'OK: {User.objects.count()} users, {Post.objects.count()} posts. '
            f'Log in as alice / bob / carol with password "{PASSWORD}", '
            f'admin with "admin123".'
        ))
