"""
所有 Redis Key 的唯一出处。

命名规则：{前缀}:{实体}:{ID}:{属性}，例如 blog:post:42:views
业务代码里不要手写 Key 字符串，统一调用这里的函数。
每一章新增的 Key 都追加在本文件中，读这个文件就能知道 Redis 里存了什么。
"""
from django.conf import settings


def _k(*parts):
    return ':'.join([settings.REDIS_KEY_PREFIX, *map(str, parts)])
