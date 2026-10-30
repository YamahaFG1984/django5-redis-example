import calendar

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import TrigramSimilarity
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView
from taggit.models import Tag

from . import redis_keys
from .forms import CommentForm, EmailPostForm, SearchForm
from .models import Post
from .services import cache as cache_service
from .services import checkin, likes, pageviews, ranking, recommend, timeline
from .services.ratelimit import rate_limit
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
    # Redis: update the visitor's interest profile for recommendations
    recommend.record_read(visitor_id, post.id)

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


# Redis: at most 5 share emails per IP per hour (fixed window)
@rate_limit('share', limit=5, window=3600, algorithm='fixed')
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
# Redis: at most 3 comments per IP per minute (sliding window)
@rate_limit('comment', limit=3, window=60, algorithm='sliding')
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


@login_required
def daily_checkin(request):
    user_id = request.user.id
    if request.method == 'POST':
        result = checkin.check_in(user_id)
        if result is None:
            messages.info(request, 'You have already checked in today.')
        else:
            messages.success(
                request,
                f"Checked in! {result['streak']} day streak, "
                f"+{result['points']} point{'s' if result['points'] > 1 else ''}.",
            )
        return redirect('blog:daily_checkin')

    today = timezone.localdate()
    days = checkin.month_calendar(user_id, today)
    first_weekday = calendar.monthrange(today.year, today.month)[0]
    return render(
        request,
        'blog/checkin.html',
        {
            'today': today,
            'days': [(i, checked) for i, checked in enumerate(days, 1)],
            'blanks': range(first_weekday),
            'stats': checkin.get_stats(user_id, today),
            'month_count': checkin.month_count(user_id, today),
            'checked_in_today_total': checkin.checked_in_count(today),
            'full_week_total': checkin.full_week_count(today),
        },
    )


def author_detail(request, username):
    author = get_object_or_404(get_user_model(), username=username)
    me = request.user
    context = {
        'author': author,
        'posts': Post.published.filter(author=author),
        'counts': timeline.follow_counts(author.id),
        'is_me': me.is_authenticated and me.id == author.id,
        'following': me.is_authenticated and timeline.is_following(me.id, author.id),
        'common': (
            timeline.common_following(me.id, author.id)
            if me.is_authenticated and me.id != author.id
            else []
        ),
    }
    return render(request, 'blog/author.html', context)


@login_required
@require_POST
def author_follow(request, username):
    author = get_object_or_404(get_user_model(), username=username)
    if author.id != request.user.id:
        if request.POST.get('action') == 'unfollow':
            timeline.unfollow(request.user.id, author.id)
        else:
            timeline.follow(request.user.id, author.id)
    return redirect('blog:author_detail', username=username)


@login_required
def my_timeline(request):
    before = request.GET.get('before')
    try:
        before = float(before) if before else None
    except ValueError:
        before = None
    posts, next_before = timeline.get_timeline(request.user.id, before)
    return render(
        request,
        'blog/timeline.html',
        {
            'posts': posts,
            'next_before': repr(next_before) if next_before is not None else None,
            'counts': timeline.follow_counts(request.user.id),
            'mutual': timeline.mutual_follows(request.user.id),
        },
    )
