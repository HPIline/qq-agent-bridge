import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sessions import SessionStore


def test_batch_writes_once():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        count = {"n": 0}
        original = os.replace

        def counting_replace(src, dst):
            if "sessions" in str(dst):
                count["n"] += 1
            return original(src, dst)

        os.replace = counting_replace
        with store.batch():
            store.touch_activity("10001")
            store.set_persona_thread("10001", "t-1")
            store.increment_persona_turns("10001")
        os.replace = original
        assert count["n"] == 1


def test_batch_nested_writes_once():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        count = {"n": 0}
        original = os.replace

        def counting_replace(src, dst):
            if "sessions" in str(dst):
                count["n"] += 1
            return original(src, dst)

        os.replace = counting_replace
        with store.batch():
            store.touch_activity("10001")
            with store.batch():
                store.set_thread("10001", "t-2")
        os.replace = original
        assert count["n"] == 1


def test_batch_persists_to_disk():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sessions.json"
        store = SessionStore(path)
        with store.batch():
            store.set_thread("10001", "t-3")
        reloaded = SessionStore(path)
        assert reloaded.get_thread("10001") == "t-3"
