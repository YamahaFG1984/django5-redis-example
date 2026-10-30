def get_visitor_id(request):
    """
    返回当前访客的唯一标识，供浏览量、推荐、搜索历史等功能使用。

    已登录用户：u:{用户ID}，换设备也是同一个人
    匿名访客：  s:{session_key}，第一次访问时创建 Session
    """
    if request.user.is_authenticated:
        return f'u:{request.user.pk}'
    if not request.session.session_key:
        request.session.save()
    return f's:{request.session.session_key}'
