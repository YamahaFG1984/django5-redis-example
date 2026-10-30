import markdown
from django import template
from django.db.models import Count
from django.utils.safestring import mark_safe

from ..models import Post
from ..services import cache as cache_service
from ..services import ranking

register = template.Library()


@register.simple_tag
def total_posts():
    return cache_service.sidebar(
        'total_posts', lambda: Post.published.count()
    )


@register.inclusion_tag('blog/post/latest_posts.html')
def show_latest_posts(count=5):
    latest_posts = cache_service.sidebar(
        f'latest:{count}',
        lambda: list(Post.published.order_by('-publish')[:count]),
    )
    return {'latest_posts': latest_posts}


@register.simple_tag
def get_most_commented_posts(count=5):
    return cache_service.sidebar(
        f'most_commented:{count}',
        lambda: list(
            Post.published.annotate(
                total_comments=Count('comments')
            ).order_by('-total_comments')[:count]
        ),
    )


@register.simple_tag
def get_hot_posts(period='week', count=5):
    return ranking.top_posts(period, count)


@register.filter(name='markdown')
def markdown_format(text):
    return mark_safe(markdown.markdown(text))
