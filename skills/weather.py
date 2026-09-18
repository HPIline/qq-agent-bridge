"""天气技能：使用 wttr.in，无需 API key。"""

from __future__ import annotations

import httpx


def skill_weather(city: str) -> str:
    if not city.strip():
        return "请提供城市名，例如：北京"
    try:
        resp = httpx.get(
            f"https://wttr.in/{city.strip()}?format=%C+%t+%w+%h",
            timeout=10.0,
        )
        resp.raise_for_status()
        return f"{city.strip()}：{resp.text.strip()}"
    except Exception as exc:
        return f"天气查询失败：{exc}"
