from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def parse_time(value: str) -> dt.time:
    hour, minute = value.strip().split(":", 1)
    return dt.time(int(hour), int(minute))


def parse_day(value: Any) -> int | None:
    v = str(value or "").strip().lower()
    mapping = {
        "1": 1,
        "周一": 1,
        "星期一": 1,
        "mon": 1,
        "monday": 1,
        "2": 2,
        "周二": 2,
        "星期二": 2,
        "tue": 2,
        "tuesday": 2,
        "3": 3,
        "周三": 3,
        "星期三": 3,
        "wed": 3,
        "wednesday": 3,
        "4": 4,
        "周四": 4,
        "星期四": 4,
        "thu": 4,
        "thursday": 4,
        "5": 5,
        "周五": 5,
        "星期五": 5,
        "fri": 5,
        "friday": 5,
        "6": 6,
        "周六": 6,
        "星期六": 6,
        "sat": 6,
        "saturday": 6,
        "7": 7,
        "0": 7,
        "周日": 7,
        "星期日": 7,
        "星期天": 7,
        "sun": 7,
        "sunday": 7,
    }
    return mapping.get(v)


def normalize_class(row: dict[str, Any]) -> dict[str, Any] | None:
    day = parse_day(row.get("day", row.get("星期", "")))
    start = str(row.get("start", row.get("开始", "")) or "").strip()
    end = str(row.get("end", row.get("结束", "")) or "").strip()
    name = str(row.get("name", row.get("课程", "")) or "").strip()
    if not day or not TIME_RE.match(start) or not name:
        return None
    if not end:
        end = start
    if not TIME_RE.match(end):
        return None
    return {
        "day": day,
        "start": start,
        "end": end,
        "name": name,
        "location": str(row.get("location", row.get("地点", "")) or "").strip(),
        "weeks": str(row.get("weeks", row.get("周次", "")) or "").strip(),
    }


def parse_csv(text: str) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(text.splitlines()))
    classes = [c for c in (normalize_class(r) for r in rows) if c]
    if not classes:
        raise ValueError("没有解析出任何有效课程（需要 day/start/name 列）")
    return classes


def parse_xlsx(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel 表格为空")
    header = [str(h or "").strip().lower() for h in rows[0]]
    keys = ["day", "start", "end", "name", "location", "weeks"]
    aliases = {
        "星期": "day",
        "开始": "start",
        "结束": "end",
        "课程": "name",
        "地点": "location",
        "周次": "weeks",
    }
    mapping: dict[int, str] = {}
    for i, h in enumerate(header):
        if h in keys:
            mapping[i] = h
        elif h in aliases:
            mapping[i] = aliases[h]
    if not mapping:
        raise ValueError("Excel 表头无法识别")
    classes = []
    for row in rows[1:]:
        item = {key: (row[i] if i < len(row) else "") for i, key in mapping.items()}
        norm = normalize_class(item)
        if norm:
            classes.append(norm)
    if not classes:
        raise ValueError("没有解析出任何有效课程")
    return classes


def load_timetable(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("classes"), list):
        raise ValueError("课表文件格式不正确：缺少 classes 列表")
    classes = [c for c in (normalize_class(c) for c in data["classes"]) if c]
    if not classes:
        raise ValueError("课表文件里没有有效课程")
    return classes


def save_timetable(path: str | os.PathLike[str], classes: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".timetable-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "classes": classes}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def weeks_match(spec: str, iso_week: int) -> bool:
    spec = (spec or "").strip()
    if not spec:
        return True
    if spec in ("单周", "单", "odd"):
        return iso_week % 2 == 1
    if spec in ("双周", "双", "even"):
        return iso_week % 2 == 0
    m = re.fullmatch(r"(\d+)-(\d+)", spec)
    if m:
        return int(m.group(1)) <= iso_week <= int(m.group(2))
    if re.fullmatch(r"[\d,\s]+", spec):
        return iso_week in {int(x) for x in re.split(r"[,\s]+", spec) if x}
    return True


def next_class(classes: list[dict[str, Any]], now: dt.datetime) -> dict[str, Any] | None:
    iso_week = now.isocalendar().week
    today_wd = now.isoweekday()
    candidates: list[tuple[dt.datetime, dict[str, Any]]] = []
    for c in classes:
        if not weeks_match(c.get("weeks", ""), iso_week):
            continue
        offset = (int(c["day"]) - today_wd) % 7
        start_dt = dt.datetime.combine(
            now.date() + dt.timedelta(days=offset), parse_time(c["start"])
        )
        if start_dt < now:
            start_dt += dt.timedelta(days=7)
        candidates.append((start_dt, c))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def format_preview(classes: list[dict[str, Any]]) -> str:
    lines = []
    for c in sorted(classes, key=lambda x: (x["day"], x["start"])):
        parts = [WEEKDAY_NAMES[int(c["day"]) - 1], f"{c['start']}-{c['end']}", c["name"]]
        if c.get("location"):
            parts.append(c["location"])
        if c.get("weeks"):
            parts.append(c["weeks"])
        lines.append(" ".join(parts))
    return "\n".join(lines)
