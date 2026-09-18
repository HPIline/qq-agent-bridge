import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_IN_EXAMPLE = ("onebot_ws_url", "full_access_qq", "api_base_url", "api_key", "model")


def _example() -> dict:
    return json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))


def test_example_config_only_contains_real_keys():
    """示例里不能有拼错的键，否则用户改半天没反应。"""
    unknown = [k for k in _example() if k not in DEFAULTS]
    assert unknown == [], f"config.example.json 里有未知键：{unknown}"


def test_example_config_covers_the_required_keys():
    example = _example()
    missing = [k for k in REQUIRED_IN_EXAMPLE if k not in example]
    assert missing == [], f"config.example.json 缺少这些必填/常用键：{missing}"
    assert example["full_access_qq"] == ["你的QQ号"]


def test_example_config_has_no_secrets_or_local_paths():
    text = (ROOT / "config.example.json").read_text(encoding="utf-8")
    assert "/Users/" not in text
    assert "C:\\Users" not in text
    assert "ghp_" not in text
    # 不允许出现看起来像真 key 的长串
    assert "sk-" not in text


def test_config_manual_documents_every_key():
    """CONFIG.md 必须覆盖 config.py 里的每个默认键（用 tools/gen_config_doc.py 生成）。"""
    text = (ROOT / "CONFIG.md").read_text(encoding="utf-8")
    missing = [k for k in DEFAULTS if f"`{k}`" not in text]
    assert missing == [], f"CONFIG.md 缺少这些键：{missing}"
