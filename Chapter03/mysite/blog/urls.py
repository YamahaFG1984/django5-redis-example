from django.urls import path

from . import views
from .feeds import LatestPostsFeed

app_name = 'blog'

urlpatterns = [
    # Post views
    path('', views.post_list, name='post_list'),
    # path('', views.PostListView.as_view(), name='post_list'),
    path(
        'tag/<slug:tag_slug>/', views.post_list, name='post_list_by_tag'
    ),
    path(
        '<int:year>/<int:month>/<int:day>/<slug:post>/',
        views.post_detail,
        name='post_detail',
    ),
    path('<int:post_id>/share/', views.post_share, name='post_share'),
    path(
        '<int:post_id>/comment/', views.post_comment, name='post_comment'
    ),
    path('feed/', LatestPostsFeed(), name='post_feed'),
    path('search/', views.post_search, name='post_search'),
    path('search/suggest/', views.search_suggest, name='search_suggest'),
    path(
        'search/history/clear/',
        views.search_history_clear,
        name='search_history_clear',
    ),
    path('ranking/', views.post_ranking, name='post_ranking'),
    path('<int:post_id>/like/', views.post_like, name='post_like'),
    path('likes/', views.my_likes, name='my_likes'),
    path('checkin/', views.daily_checkin, name='daily_checkin'),
    path('author/<str:username>/', views.author_detail, name='author_detail'),
    path(
        'author/<str:username>/follow/',
        views.author_follow,
        name='author_follow',
    ),
    path('timeline/', views.my_timeline, name='my_timeline'),
    path('notifications/', views.my_notifications, name='my_notifications'),
]
