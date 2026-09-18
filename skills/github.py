"""GitHub 技能：查询公开仓库信息，可选 token 提高限额。"""

from __future__ import annotations

import httpx


def skill_github_repo(repo: str, token: str = "") -> str:
    repo = repo.strip().strip("/")
    if not repo:
        return "请提供仓库名，例如：owner/repo"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        return (
            f"{data.get('full_name')}：{data.get('description') or '无描述'} "
            f"（⭐ {data.get('stargazers_count', 0)}，Fork {data.get('forks_count', 0)}）"
        )
    except Exception as exc:
        return f"GitHub 查询失败：{exc}"
