"""轻量本地知识库：扫描文档 → SQLite FTS5 索引 → 搜索/作为助手工具。

第一版用 FTS5 关键词检索，接口预留向量化升级。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from state_db import StateDB

_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 80


def _chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += max(1, size - overlap)
    return chunks


async def scan_docs(
    dirs: Iterable[str | Path],
    db: StateDB,
    extensions: tuple[str, ...] = (".md", ".txt", ".pdf"),
) -> int:
    db.clear_documents()
    count = 0
    for base in dirs:
        base_path = Path(base)
        if not base_path.exists():
            continue
        for path in base_path.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            try:
                if path.suffix.lower() == ".pdf":
                    from pdf_utils import extract_pdf_text

                    text = await extract_pdf_text(
                        path,
                        max_pages=10,
                        timeout=120,
                        max_chars=8000,
                    )
                else:
                    text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logging.warning("知识库索引失败：%s %s", path, exc)
                continue
            for idx, chunk in enumerate(_chunk_text(text)):
                db.add_document(str(path), idx, path.name, chunk)
                count += 1
    return count


def search(db: StateDB, query: str, limit: int = 5) -> list[dict[str, Any]]:
    return db.search_documents(query, limit=limit)


def search_knowledge(db: StateDB, query: str, limit: int = 5) -> str:
    hits = db.search_documents(query, limit=limit)
    if not hits:
        return "（本地知识库没有找到相关内容）"
    parts = []
    for hit in hits:
        parts.append(f"【{hit['title']}】\n{hit.get('snippet') or ''}")
    return "\n\n".join(parts)


class RagIndex:
    def __init__(self, db: StateDB):
        self.db = db

    async def rebuild(self, dirs: Iterable[str | Path]) -> int:
        return await scan_docs(dirs, self.db)

    def query(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.db.search_documents(query, limit=limit)
