"""RSS 技能：抓取并解析 RSS 标题。"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx


def skill_rss_headlines(url: str, limit: int = 5) -> str:
    if not url.strip():
        return "请提供 RSS 地址"
    try:
        resp = httpx.get(url.strip(), timeout=10.0, follow_redirects=True)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                items.append(title_el.text.strip())
            if len(items) >= max(1, min(int(limit), 20)):
                break
        if not items:
            return "RSS 中没有解析到条目"
        return "\n".join(f"- {t}" for t in items)
    except Exception as exc:
        return f"RSS 解析失败：{exc}"
