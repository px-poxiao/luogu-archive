"""Markdown + LaTeX + 洛谷专有语法 · 渲染管线。

- core.py     基于 markdown-it-py 构建的核心渲染器（单例）
- user_mention.py   @[name](/user/uid) 提及语法 + 脱敏
- quote_reply.py    `|| @[name](/user/uid) : text` 引用回复语法
- luogu_bbcode.py   [color][user][template] 等老式 BBCode 兼容
- katex_inline.py   把 `$...$` / `$$...$$` 标记为 KaTeX 块（前端渲染）
- rewrite_link.py   把洛谷原站链接改写成本站路径
- sanitize.py       限制 HTML 白名单（防 XSS）
"""
