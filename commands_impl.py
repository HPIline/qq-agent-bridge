"""QQ 对话命令聚合入口：导入各领域命令模块完成注册。"""

from __future__ import annotations

import commands_legacy_impl  # noqa: F401  注册会话/课表等旧命令
import commands_reminders_impl  # noqa: F401  注册提醒命令
import commands_skills_impl  # noqa: F401  注册晨报/技能/知识库命令
import commands_tasks_impl  # noqa: F401  注册后台任务命令
import commands_todos_impl  # noqa: F401  注册待办/日历命令
