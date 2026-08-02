"""ORM 模型包。

组织方式：按领域分文件
- luogu_content: 洛谷内容表（articles/pastes/feeds/judgements/problems）
- luogu_user:    洛谷用户主表 + 历史 + 奖项/Elo/咕值/打卡
- site_user:     本站用户 + 评论 + 关注
- admin:         管理员 + 审计日志 + 爬取账号
- task:          爬虫任务审计 + 保存请求审计 + 删除申请工单

所有模型从 app.core.db.Base 继承。
"""
from app.core.db import Base
from app.models.contest import Contest, ContestParticipant, ContestProblem
from app.models.admin import (
    Admin,
    AdminAuditLog,
    CrawlerAccount,
    SiteAnnouncement,
)
from app.models.luogu_content import (
    Article,
    ArticleVersion,
    Feed,
    FeedCompletion,
    Judgement,
    Paste,
    PasteVersion,
    Problem,
    ProblemSolutionHistory,
)
from app.models.luogu_user import (
    LuoguUser,
    UserDailyActivity,
    UserEloHistory,
    UserGuHistory,
    UserIntroVersion,
    UserNameVersion,
    UserNameViolation,
    UserNumericSnapshot,
    UserProfileChange,
    UserPrize,
)
from app.models.site_user import (
    SiteSession,
    SiteUser,
    SiteUserFollow,
)
from app.models.task import (
    CrawlTask,
    SaveRequest,
    TakedownRequest,
)

__all__ = [
    "Admin",
    "AdminAuditLog",
    "Article",
    "ArticleVersion",
    "Base",
    "CrawlTask",
    "CrawlerAccount",
    "Contest",
    "ContestParticipant",
    "ContestProblem",
    "Feed",
    "FeedCompletion",
    "Judgement",
    "LuoguUser",
    "Paste",
    "PasteVersion",
    "Problem",
    "ProblemSolutionHistory",
    "SaveRequest",
    "SiteAnnouncement",
    "SiteComment",
    "SiteSession",
    "SiteUser",
    "SiteUserFollow",
    "TakedownRequest",
    "UserDailyActivity",
    "UserEloHistory",
    "UserGuHistory",
    "UserIntroVersion",
    "UserNameVersion",
    "UserNameViolation",
    "UserNumericSnapshot",
    "UserProfileChange",
    "UserPrize",
]
