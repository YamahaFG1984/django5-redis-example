"""
模型变化时同步 Redis 中的派生数据。每一章在这里添加自己的处理函数。
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Post
from .services import ranking


@receiver(post_save, sender=Post)
def post_saved(sender, instance, **kwargs):
    if instance.status != Post.Status.PUBLISHED:
        # step-04 下线的文章从排行榜移除
        ranking.remove_post(instance.id)


@receiver(post_delete, sender=Post)
def post_deleted(sender, instance, **kwargs):
    ranking.remove_post(instance.id)
