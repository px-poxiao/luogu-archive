"""核心渲染器。

使用 markdown-it-py 作为基础引擎，加装洛谷专有语法插件。
对外只暴露 render_markdown() 一个函数。

性能：markdown-it 是纯 Python 实现，但对于文章级（< 50KB）的内容足够快。
"""
from __future__ import annotations

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from app.render.context import RenderContext
from app.render.plugins.luogu_bbcode import luogu_bbcode_plugin
from app.render.plugins.quote_reply import quote_reply_plugin
from app.render.plugins.rewrite_link import rewrite_link_plugin
from app.render.plugins.user_mention import user_mention_plugin


def _build_md() -> MarkdownIt:
    """构造并配置 MarkdownIt 实例。"""
    md = MarkdownIt(
        "commonmark",
        {
            "html": False,          # 默认禁 HTML，由 sanitize 白名单放过必要标签
            "breaks": True,         # 软换行转 <br>（洛谷如此）
            "linkify": True,        # 自动识别裸 URL
            "typographer": False,
        },
    )
    # 启用 CommonMark 外常用扩展
    md.enable(["strikethrough", "table"])
    # 插件
    md.use(anchors_plugin, min_level=2, max_level=4, permalink=False)
    md.use(footnote_plugin)
    md.use(deflist_plugin)
    md.use(tasklists_plugin)
    # 洛谷专有
    md.use(user_mention_plugin)   # @[name](/user/uid)
    md.use(quote_reply_plugin)    # || @xxx : ... （顶层 block）
    md.use(luogu_bbcode_plugin)   # [color][user][template] ...
    md.use(rewrite_link_plugin)   # luogu 链接 → 本站
    # 注意：LaTeX 不在后端渲染，保留 `$...$` / `$$...$$` 原样输出到 HTML；
    # 前端装 KaTeX 自动扫描 class=math 的节点，或纯文本被 Nuxt 的 KaTeX 插件处理。
    return md


# 进程级单例（线程/协程安全，MarkdownIt 自身是只读的）
_md_singleton: MarkdownIt | None = None


def _get_md() -> MarkdownIt:
    global _md_singleton
    if _md_singleton is None:
        _md_singleton = _build_md()
    return _md_singleton


def render_markdown(source: str, ctx: RenderContext | None = None) -> str:
    """把 markdown 文本渲染为 HTML。

    ctx：可选，决定脱敏与链接改写的行为。
    """
    md = _get_md()
    env: dict = {"luogu_ctx": ctx or RenderContext()}
    return md.render(source or "", env)
