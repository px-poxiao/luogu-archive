"""渲染上下文。

渲染时需要几个额外依赖：
- 用户名违规隐藏逻辑 → 需要查询 DB（是否应当脱敏）
- 是否为管理员视角 → 绕过脱敏
- 本站 URL 基础前缀 → 链接改写

为避免插件层耦合 DB，引入 RenderContext：
- 调用渲染前，业务层预先从 DB 查出"涉及的 uid/name 需要脱敏的集合"
- RenderContext 持有这个集合 + 当前视角 + 其他开关
- 所有插件只读 RenderContext，不直接查 DB
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RenderContext:
    """渲染时的上下文。"""

    # 管理员视角 → 忽略脱敏
    is_admin_view: bool = False

    # "当前这个 name 应脱敏"：key = (uid, name)，用于提及语法精确匹配
    # 值为 True 表示该名字在当前 uid 的 name_versions 表里是 is_hidden=true
    hidden_name_map: dict[tuple[int, str], bool] = field(default_factory=dict)

    # "这个 uid 当前名也该脱敏"（当前 name 被判定为 hidden 时）
    hidden_current_uid: set[int] = field(default_factory=set)

    # 本站 URL 前缀（用于链接改写）
    site_origin: str = ""

    def should_mask(self, uid: int, name: str | None = None) -> bool:
        """判断某个提及是否应脱敏。"""
        if self.is_admin_view:
            return False
        if uid in self.hidden_current_uid:
            return True
        if name is not None and self.hidden_name_map.get((uid, name)):
            return True
        return False
