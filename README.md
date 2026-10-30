# Django 5 × Redis 实战教学项目

基于《Django 5 By Example》第 3 章的博客项目（`Chapter03/`），逐步加入 10 个基于 Redis 的功能，
覆盖 STRING、HASH、LIST、SET、ZSET、Bitmap、HyperLogLog、Stream 和 Lua 脚本。

**文档入口：用浏览器打开 [`docs/index.html`](docs/index.html)**（图表由 Mermaid 渲染，需要联网加载 CDN）。

| Tag | 内容 | 文档 |
| --- | --- | --- |
| `step-00-baseline` | 原书第 3 章代码 | — |
| `step-01-docs` | PRD、系统设计文档 | `docs/01-prd.html`、`docs/02-design.html` |
| `step-02-redis-setup` | 接入 Redis：连接池、Key 规范、测试基类、演示数据 | `docs/features/02-redis-setup.html` |
| `step-03-page-views` | 浏览量 PV/UV：INCR、SET NX EX、HyperLogLog | `docs/features/03-page-views.html` |
| `step-04-hot-ranking` | 排行榜：ZINCRBY、ZUNIONSTORE | `docs/features/04-hot-ranking.html` |
| `step-05-cache` | 缓存：Cache-Aside、穿透/击穿/雪崩、分布式锁 | `docs/features/05-cache.html` |
| `step-06-likes` | 点赞：SET + ZSET 双向索引、ZMSCORE | `docs/features/06-likes.html` |
| `step-07-checkin` | 签到：Bitmap、BITFIELD、BITOP、Hash | `docs/features/07-checkin.html` |
| `step-08-follow-timeline` | 关注与时间线：写扩散、游标分页、SINTER | `docs/features/08-timeline.html` |
| `step-09-recommend` | 推荐：兴趣画像、加权 ZUNIONSTORE、ZDIFFSTORE | `docs/features/09-recommend.html` |
| `step-10-rate-limit` | 限流：固定窗口、滑动窗口、Lua | `docs/features/10-rate-limit.html` |
| `step-11-search` | 热搜、搜索历史、ZRANGEBYLEX 联想 | `docs/features/11-search.html` |
| `step-12-notifications` | 评论通知：Stream 消费组、XAUTOCLAIM | `docs/features/12-notifications.html` |

```bash
git diff step-02-redis-setup step-03-page-views -- Chapter03   # 看某一步改了什么
cd Chapter03 && docker compose up -d web_run web_worker        # 启动
docker compose exec web_run python /code/mysite/manage.py seed_demo
```

文档中的代码片段由 `python3 docs/tools/sync_code.py` 从源码同步。
