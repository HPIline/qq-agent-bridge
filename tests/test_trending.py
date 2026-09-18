import asyncio
import datetime as dt

from trending import (
    extract_image_urls,
    fetch_trending_context,
    format_trending_context,
    get_cached_trending_context,
    parse_grok_json,
    run_search_sync,
)


def test_extract_image_urls():
    text = "![a](https://example.com/a.jpg) 文字 ![b](https://example.com/b.png)"
    assert extract_image_urls(text) == [
        "https://example.com/a.jpg",
        "https://example.com/b.png",
    ]


def test_parse_grok_json():
    raw = '{"text": "热梗内容", "citations": ["https://example.com"], "tool_calls": []}'
    data = parse_grok_json(raw)
    assert data["text"] == "热梗内容"
    assert data["citations"] == ["https://example.com"]


def test_format_trending_context_includes_images():
    data = {
        "text": "最近流行“爱你老己”",
        "citations": ["https://example.com"],
        "image_urls": ["https://example.com/meme.jpg"],
    }
    out = format_trending_context(data, include_images=True)
    assert "最近流行“爱你老己”" in out
    assert "https://example.com/meme.jpg" in out


def test_fetch_trending_context_uses_cache(monkeypatch):
    cache = {
        "ts": (dt.datetime.now() - dt.timedelta(minutes=1)).timestamp(),
        "text": "cached 热梗",
    }
    called = False

    async def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        return {"text": "不应调用", "citations": [], "image_urls": []}

    monkeypatch.setattr("trending.run_search_sync", fake_run)
    result = asyncio.run(fetch_trending_context({}, cache=cache))
    assert result == "cached 热梗"
    assert called is False


def test_fetch_trending_context_calls_search_and_caches(monkeypatch):
    cache = {}

    def fake_run(query, image_search=False, timeout=90.0, script_path="", python_path=""):
        assert image_search is True
        return {
            "text": "新梗：活人感",
            "citations": ["https://example.com"],
            "image_urls": ["https://example.com/meme.jpg"],
        }

    monkeypatch.setattr("trending.run_search_sync", fake_run)
    result = asyncio.run(
        fetch_trending_context(
            {
                "proactive_trending_query": "今天有什么热梗",
                "proactive_trending_image_search_enabled": True,
                "proactive_news_enabled": False,
                "proactive_art_enabled": False,
            },
            cache=cache,
        )
    )
    assert "新梗：活人感" in result
    assert "https://example.com/meme.jpg" in result
    assert "ts" in cache
    assert "text" in cache


def test_fetch_trending_context_disabled_returns_empty():
    result = asyncio.run(
        fetch_trending_context({"proactive_trending_enabled": False}, cache={})
    )
    assert result == ""


def test_fetch_trending_context_failure_returns_empty(monkeypatch):
    def fake_run(*args, **kwargs):
        raise RuntimeError("search down")

    monkeypatch.setattr("trending.run_search_sync", fake_run)
    result = asyncio.run(
        fetch_trending_context(
            {
                "proactive_trending_enabled": True,
                "proactive_news_enabled": False,
                "proactive_art_enabled": False,
            },
            cache={},
        )
    )
    assert result == ""


def test_fetch_trending_context_builds_news_pool(monkeypatch):
    cache = {}

    def fake_run(query, image_search=False, timeout=90.0, script_path="", python_path=""):
        if "AI" in query:
            return {"text": "AI 新闻正文", "citations": [], "image_urls": []}
        if "推荐画师" in query:
            return {"text": "画师推荐正文", "citations": [], "image_urls": []}
        if "Pixiv 画师图片" in query:
            return {
                "text": "画师新作正文",
                "citations": [],
                "image_urls": ["https://example.com/art.jpg"],
            }
        return {
            "text": "热梗正文",
            "citations": [],
            "image_urls": ["https://example.com/meme.jpg"],
        }

    monkeypatch.setattr("trending.run_search_sync", fake_run)
    result = asyncio.run(
        fetch_trending_context(
            {
                "proactive_trending_query": "热梗",
                "proactive_trending_image_search_enabled": True,
                "proactive_news_enabled": True,
                "proactive_news_query": "AI 新闻",
                "proactive_art_enabled": True,
                "proactive_art_query": "推荐画师",
                "proactive_art_image_query": "Pixiv 画师图片",
                "proactive_artists": [],
            },
            cache=cache,
        )
    )
    assert "今日热梗/梗图" in result
    assert "AI/科技要闻" in result
    assert "二次元画师推荐" in result
    assert "画师新作/新图" in result
    assert "https://example.com/meme.jpg" in result
    assert "https://example.com/art.jpg" in result


def test_get_cached_trending_context_returns_fresh_cache():
    cache = {
        "ts": (dt.datetime.now() - dt.timedelta(minutes=1)).timestamp(),
        "text": "cached 热梗",
    }
    assert get_cached_trending_context({}, cache=cache) == "cached 热梗"


def test_get_cached_trending_context_disabled_or_stale_returns_empty():
    stale_cache = {
        "ts": (dt.datetime.now() - dt.timedelta(days=1)).timestamp(),
        "text": "old 热梗",
    }
    assert get_cached_trending_context({}, cache=stale_cache) == ""
    assert (
        get_cached_trending_context(
            {"proactive_trending_enabled": False}, cache=stale_cache
        )
        == ""
    )


def test_prefetch_trending_starts_background_fetch(monkeypatch):
    import trending

    cache: dict = {}

    async def fake_fetch(cfg, cache=None, now=None):
        cache["text"] = "prefetched 热梗"
        cache["ts"] = dt.datetime.now().timestamp()
        return cache["text"]

    monkeypatch.setattr(trending, "fetch_trending_context", fake_fetch)
    trending._PREFETCH_TASK = None

    async def scenario():
        trending.prefetch_trending({"proactive_trending_enabled": True}, cache=cache)
        await asyncio.sleep(0)
        return cache.get("text")

    assert asyncio.run(scenario()) == "prefetched 热梗"


def test_run_search_sync_strips_proxy_env(monkeypatch):
    from types import SimpleNamespace

    captured: dict = {}
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("GROK_API_KEY", "test-key")

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return SimpleNamespace(
            returncode=0,
            stdout='{"text": "ok", "citations": [], "tool_calls": []}',
            stderr="",
        )

    monkeypatch.setattr("trending.subprocess.run", fake_run)
    result = run_search_sync("最近有什么热梗")
    assert result["text"] == "ok"
    assert "HTTPS_PROXY" not in captured["env"]
    assert "HTTP_PROXY" not in captured["env"]