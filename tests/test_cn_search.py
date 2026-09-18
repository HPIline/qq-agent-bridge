import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cn_search import extract_results, format_results, search_cn_images

SAMPLE_HTML = """
<ol id="b_results">
<li class="b_algo"><h2><a href="https://baike.baidu.com/item/A">标题A</a></h2><p>摘要A内容</p></li>
<li class="b_algo"><h2><a href="https://example.com/B">标题B</a></h2><p>摘要B内容</p></li>
</ol>
"""


def test_extract_results_parses_bing_blocks():
    results = extract_results(SAMPLE_HTML)
    assert len(results) == 2
    assert results[0]["title"] == "标题A"
    assert results[0]["url"] == "https://baike.baidu.com/item/A"
    assert results[0]["snippet"] == "摘要A内容"


def test_format_results_builds_readable_text():
    results = extract_results(SAMPLE_HTML)
    text = format_results(results)
    assert "标题A" in text
    assert "https://baike.baidu.com/item/A" in text
    assert "摘要B内容" in text


def test_format_results_empty():
    assert "没有返回结果" in format_results([])


def test_search_cn_images_parses_murl(monkeypatch):
    class FakeResp:
        text = (
            'xxx murl&quot;:&quot;https://example.com/a.jpg&quot; yyy '
            'murl&quot;:&quot;https://example.com/b.png&quot;'
        )

        def raise_for_status(self):
            pass

    monkeypatch.setattr("cn_search.httpx.get", lambda *args, **kwargs: FakeResp())
    assert search_cn_images("梗图") == [
        "https://example.com/a.jpg",
        "https://example.com/b.png",
    ]



