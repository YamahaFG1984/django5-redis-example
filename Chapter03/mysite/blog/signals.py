"""
模型变化时同步 Redis 中的派生数据。每一章在这里添加自己的处理函数。
"""
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Comment, Post
from .services import cache as cache_service
from .services import likes, notifications, ranking, recommend, search, timeline


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

    # step-09 更新标签倒排索引（下线的文章会被移出）
    recommend.index_post(instance)
    # step-11 更新标题联想索引（标题可能改过，旧的要删掉）
    search.index_title(instance, getattr(instance, '_old', None))

    if instance.status == Post.Status.PUBLISHED:
        # step-08 推送到粉丝的时间线
        timeline.publish(instance)
    else:
        # step-04 下线的文章从排行榜移除
        ranking.remove_post(instance.id)
        # step-08 从时间线移除
        timeline.unpublish(instance)


@receiver(post_delete, sender=Post)
def post_deleted(sender, instance, **kwargs):
    cache_service.invalidate_post(instance)
    cache_service.invalidate_sidebar()
    ranking.remove_post(instance.id)
    # step-06 清理点赞关系
    likes.remove_post(instance.id)
    # step-08 从时间线移除
    timeline.unpublish(instance)
    # step-09 移出标签索引
    recommend.remove_post(instance.id)
    # step-11 移出标题联想索引
    search.remove_title(instance)


@receiver(m2m_changed, sender=Post.tags.through)
def post_tags_changed(sender, instance, action, **kwargs):
    # step-09 Admin 中先保存文章、再保存标签，所以标签变化要单独处理
    if action in ('post_add', 'post_remove', 'post_clear') and isinstance(instance, Post):
        recommend.index_post(instance)


@receiver([post_save, post_delete], sender=Comment)
def comment_changed(sender, instance, **kwargs):
    # step-05 评论数变了，「评论最多」的侧边栏要刷新
    cache_service.invalidate_sidebar()


@receiver(post_save, sender=Comment)
def comment_created(sender, instance, created, **kwargs):
    if created and instance.active:
        # step-12 事务提交之后再发事件：否则 worker 可能比数据库提交还快，查不到这条评论
        transaction.on_commit(lambda: notifications.publish_comment(instance))
