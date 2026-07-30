"""Shared stable values for owner-contact relations.

This module intentionally contains no UI, API, repository, or database code so
both the Windows client and FastAPI validation can use the same stable values
without crossing architectural layers.
"""

RELATIONSHIP_TYPES = (
    "配偶",
    "前配偶",
    "父親",
    "母親",
    "兒子",
    "女兒",
    "兄弟",
    "姊妹",
    "孫子",
    "孫女",
    "女婿",
    "媳婦",
    "代理人",
    "代書",
    "共同持有人",
    "鄰居",
    "里長",
    "其他",
)
