"""
模型变化时同步 Redis 中的派生数据。每一章在这里添加自己的处理函数。
"""
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Comment, Post
from .services import cache as cache_service
from .services import ranking


@receiver(pre_save, sender=Post)
def post_before_save(sender, instance, **kwargs):
    # step-05 记住修改前的文章：如果 slug 或发布日期变了，旧的缓存 key 也要删
    instance._old = Post.objects.filter(pk=instance.pk).first() if instance.pk else None


@receiver(post_save, sender=Post)
def post_saved(sender, instance, **kwargs):
    # step-05 删除缓存（而不是更新缓存），下次读取时自然会重新加载
    cache_service.invalidate_post(instance)
    if getattr(instance, '_old', None) is not None:
        cache_service.invalidate_post(instance._old)
    cache_service.invalidate_sidebar()

    if instance.status != Post.Status.PUBLISHED:
        # step-04 下线的文章从排行榜移除
        ranking.remove_post(instance.id)


@receiver(post_delete, sender=Post)
def post_deleted(sender, instance, **kwargs):
    cache_service.invalidate_post(instance)
    cache_service.invalidate_sidebar()
    ranking.remove_post(instance.id)


@receiver([post_save, post_delete], sender=Comment)
def comment_changed(sender, instance, **kwargs):
    # step-05 评论数变了，「评论最多」的侧边栏要刷新
    cache_service.invalidate_sidebar()
