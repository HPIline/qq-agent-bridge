import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from timetable import (
    format_preview,
    load_timetable,
    next_class,
    parse_csv,
    parse_day,
    save_timetable,
    weeks_match,
)


def test_parse_day():
    assert parse_day("周一") == 1
    assert parse_day("星期日") == 7
    assert parse_day("0") == 7
    assert parse_day("5") == 5
    assert parse_day("随便") is None


def test_parse_csv():
    text = "day,start,end,name,location,weeks\n1,08:00,09:40,高等数学,教1-101,\n2,10:00,11:40,线性代数,,双周\n"
    classes = parse_csv(text)
    assert classes[0] == {
        "day": 1,
        "start": "08:00",
        "end": "09:40",
        "name": "高等数学",
        "location": "教1-101",
        "weeks": "",
    }
    assert classes[1]["weeks"] == "双周"
    with pytest.raises(ValueError):
        parse_csv("day,start,end\n1,08:00,09:40\n")


def test_weeks_match():
    assert weeks_match("", 10) is True
    assert weeks_match("单周", 11) is True
    assert weeks_match("单周", 10) is False
    assert weeks_match("双周", 10) is True
    assert weeks_match("1-8", 5) is True
    assert weeks_match("1-8", 9) is False
    assert weeks_match("1,3,5", 3) is True
    assert weeks_match("1,3,5", 4) is False
    assert weeks_match("乱写", 4) is True


def test_next_class_skips_past_today_and_picks_today():
    now = dt.datetime(2026, 8, 6, 10, 0)  # 周四
    day = now.isoweekday()
    classes = [
        {
            "day": day,
            "start": "09:00",
            "end": "09:40",
            "name": "已过去",
            "location": "",
            "weeks": "",
        },
        {
            "day": day,
            "start": "10:15",
            "end": "11:40",
            "name": "下一节",
            "location": "教1",
            "weeks": "",
        },
        {
            "day": day,
            "start": "08:00",
            "end": "09:00",
            "name": "单周课",
            "location": "",
            "weeks": "单周",
        },
    ]
    found = next_class(classes, now)
    assert found["name"] == "下一节"


def test_save_load_roundtrip_and_preview():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "timetable.json"
        classes = [
            {
                "day": 1,
                "start": "08:00",
                "end": "09:40",
                "name": "高等数学",
                "location": "教1-101",
                "weeks": "",
            }
        ]
        save_timetable(path, classes)
        assert load_timetable(path) == classes
        assert "周一" in format_preview(classes)
        assert "高等数学" in format_preview(classes)


def test_parse_xlsx():
    openpyxl = pytest.importorskip("openpyxl")
    from timetable import parse_xlsx

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "timetable.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["day", "start", "end", "name", "location", "weeks"])
        ws.append([1, "08:00", "09:40", "高等数学", "教1-101", ""])
        wb.save(path)
        classes = parse_xlsx(str(path))
        assert classes == [
            {
                "day": 1,
                "start": "08:00",
                "end": "09:40",
                "name": "高等数学",
                "location": "教1-101",
                "weeks": "",
            }
        ]
