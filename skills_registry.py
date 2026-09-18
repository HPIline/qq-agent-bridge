"""外部技能注册表：加载 skills/ 下的技能并包装成助手可调用的工具。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from skills import github, rss, weather


def _wrap(
    name: str, description: str, parameters: dict[str, Any], entrypoint: Callable[..., str]
) -> Any:
    from agno.tools import Function

    return Function(
        name=name,
        description=description,
        parameters=parameters,
        entrypoint=entrypoint,
    )


def load_skills(cfg: dict[str, Any]) -> list[Any]:
    enabled = set(cfg.get("skills_enabled") or [])
    tools: list[Any] = []

    if "weather" in enabled:
        tools.append(
            _wrap(
                "weather",
                "查询天气，参数 city 为城市名，如“北京”。",
                {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名，例如：北京、上海"}
                    },
                    "required": ["city"],
                },
                weather.skill_weather,
            )
        )

    if "rss" in enabled:
        tools.append(
            _wrap(
                "rss_headlines",
                "抓取 RSS 地址并返回标题列表。",
                {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "RSS/Atom 地址"},
                        "limit": {"type": "integer", "description": "最多返回标题数", "default": 5},
                    },
                    "required": ["url"],
                },
                rss.skill_rss_headlines,
            )
        )

    if "github" in enabled:
        token = str(cfg.get("github_token") or "")

        def github_repo(repo: str) -> str:
            return github.skill_github_repo(repo, token=token)

        tools.append(
            _wrap(
                "github_repo",
                "查询 GitHub 公开仓库信息，参数为 owner/repo。",
                {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "仓库名，例如：owner/repo"}
                    },
                    "required": ["repo"],
                },
                github_repo,
            )
        )

    return tools


def get_skill_index() -> str:
    """给模型的技能清单（只列出 skills_enabled 里启用的技能）。"""
    return (
        "可用外部技能：\n"
        "- weather(city)：查询天气\n"
        "- rss_headlines(url, limit=5)：抓取 RSS 标题\n"
        "- github_repo(repo)：查询 GitHub 仓库\n"
        "更多技能可以在 skills/ 下自行添加，并在 config.json 的 skills_enabled 里启用。"
    )
