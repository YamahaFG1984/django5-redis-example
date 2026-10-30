from django.contrib.postgres.search import TrigramSimilarity
from django.core.cache import cache
from django.core.mail import send_mail
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import ListView
from taggit.models import Tag

from . import redis_keys
from .forms import CommentForm, EmailPostForm, SearchForm
from .models import Post
from .services import cache as cache_service
from .services import likes, pageviews, ranking
from .visitors import get_visitor_id


def post_list(request, tag_slug=None):
    post_list = Post.published.all()
    tag = None
    if tag_slug:
        tag = get_object_or_404(Tag, slug=tag_slug)
        post_list = post_list.filter(tags__in=[tag])
    # Pagination with 3 posts per page
    paginator = Paginator(post_list, 3)
    page_number = request.GET.get('page', 1)
    try:
        posts = paginator.page(page_number)
    except PageNotAnInteger:
        # If page_number is not an integer get the first page
        posts = paginator.page(1)
    except EmptyPage:
        # If page_number is out of range get last page of results
        posts = paginator.page(paginator.num_pages)
    # Redis: view counters for the whole page in one MGET
    pageviews.attach_view_counts(posts)
    # Redis: like counts + "did I like it" in one pipeline
    likes.attach_like_info(posts, request.user)
    return render(
        request,
        'blog/post/list.html',
        {
            'posts': posts,
            'tag': tag
        }
    )


def post_detail(request, year, month, day, post):
    # Redis: cache-aside lookup (also caches "not found")
    post = cache_service.get_published_post(year, month, day, post)
    if post is None:
        raise Http404('No Post matches the given query.')

    # Redis: count this view (deduplicated per visitor)
    visitor_id = get_visitor_id(request)
    if pageviews.record_view(post, visitor_id):
        # Redis: only counted views raise the post in the rankings
        ranking.record_view(post.id)

    # List of active comments for this post
    comments = post.comments.filter(active=True)
    # Form for users to comment
    form = CommentForm()

    # List of similar posts (cached for 10 minutes)
    similar_posts = cache.get_or_set(
        redis_keys.cache_post_similar(post.id),
        lambda: list(_similar_posts(post)),
        cache_service.jitter(600),
    )

    return render(
        request,
        'blog/post/detail.html',
        {
            'post': post,
            'comments': comments,
            'form': form,
            'similar_posts': similar_posts,
            'views': pageviews.get_views(post),
            'unique_visitors': pageviews.get_uv(post),
            'like_count': likes.like_count(post.id),
            'liked': (
                request.user.is_authenticated
                and likes.has_liked(request.user.id, post.id)
            ),
        },
    )


def _similar_posts(post):
    post_tags_ids = post.tags.values_list('id', flat=True)
    similar_posts = Post.published.filter(
        tags__in=post_tags_ids
    ).exclude(id=post.id)
    return similar_posts.annotate(
        same_tags=Count('tags')
    ).order_by('-same_tags', '-publish')[:4]


class PostListView(ListView):
    """
    Alternative post list view
    """

    queryset = Post.published.all()
    context_object_name = 'posts'
    paginate_by = 3
    template_name = 'blog/post/list.html'


def post_share(request, post_id):
    # Retrieve post by id
    post = get_object_or_404(
        Post,
        id=post_id,
        status=Post.Status.PUBLISHED
    )
    sent = False

    if request.method == 'POST':
        # Form was submitted
        form = EmailPostForm(request.POST)
        if form.is_valid():
            # Form fields passed validation
            cd = form.cleaned_data
            post_url = request.build_absolute_uri(
                post.get_absolute_url()
            )
            subject = (
                f"{cd['name']} ({cd['email']}) "
                f"recommends you read {post.title}"
            )
            message = (
                f"Read {post.title} at {post_url}\n\n"
                f"{cd['name']}'s comments: {cd['comments']}"
            )
            send_mail(
                subject=subject,
                message=message,
                from_email=None,
                recipient_list=[cd['to']],
            )
            sent = True

    else:
        form = EmailPostForm()
    return render(
        request,
        'blog/post/share.html',
        {
            'post': post,
            'form': form,
            'sent': sent
        },
    )


@require_POST
def post_comment(request, post_id):
    post = get_object_or_404(
        Post,
        id=post_id,
        status=Post.Status.PUBLISHED
    )
    comment = None
    # A comment was posted
    form = CommentForm(data=request.POST)
    if form.is_valid():
        # Create a Comment object without saving it to the database
        comment = form.save(commit=False)
        # Assign the post to the comment
        comment.post = post
        # Save the comment to the database
        comment.save()
    return render(
        request,
        'blog/post/comment.html',
        {
            'post': post,
            'form': form,
            'comment': comment
        },
    )


def post_search(request):
    form = SearchForm()
    query = None
    results = []

    if 'query' in request.GET:
        form = SearchForm(request.GET)
        if form.is_valid():
            query = form.cleaned_data['query']
            results = (
                Post.published.annotate(
                    similarity=TrigramSimilarity('title', query),
                )
                .filter(similarity__gt=0.1)
                .order_by('-similarity')
            )

    return render(
        request,
        'blog/post/search.html',
        {
            'form': form,
            'query': query,
            'results': results
        },
    )


def post_ranking(request):
    boards = [
        ('Today', ranking.top_posts('day')),
        ('Last 7 days', ranking.top_posts('week')),
        ('All time', ranking.top_posts('total')),
    ]
    return render(request, 'blog/post/ranking.html', {'boards': boards})


@login_required
@require_POST
def post_like(request, post_id):
    post = get_object_or_404(
        Post,
        id=post_id,
        status=Post.Status.PUBLISHED
    )
    if request.POST.get('action') == 'unlike':
        likes.unlike(request.user.id, post.id)
    else:
        likes.like(request.user.id, post.id)
    return redirect(post)


@login_required
def my_likes(request):
    posts = likes.liked_posts(request.user.id)
    return render(request, 'blog/post/likes.html', {'posts': posts})
