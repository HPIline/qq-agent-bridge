"""视频消息段解析与缓冲测试。"""

from __future__ import annotations

from message_utils import MEDIA_MARKER_RE, extract_media_markers, extract_private_message


def _private_event(message: list[dict]) -> dict:
    return {
        "post_type": "message",
        "message_type": "private",
        "message_id": "msg-video-1",
        "user_id": "10001",
        "message": message,
    }


def test_extract_private_message_parses_video_segment():
    event = _private_event(
        [
            {"type": "text", "data": {"text": "看看这个视频"}},
            {
                "type": "video",
                "data": {
                    "url": "https://example.com/a.mp4",
                    "file": "https://example.com/a.mp4",
                    "path": "",
                    "name": "a.mp4",
                },
            },
        ]
    )
    info = extract_private_message(event)
    assert info is not None
    assert info["text"] == "看看这个视频"
    assert info["videos"] == [
        {
            "url": "https://example.com/a.mp4",
            "file": "https://example.com/a.mp4",
            "path": "",
            "name": "a.mp4",
        }
    ]


def test_extract_private_message_ignores_video_without_source():
    event = _private_event([{"type": "video", "data": {"name": "无来源.mp4"}}])
    info = extract_private_message(event)
    assert info is not None
    assert info["videos"] == []


def test_video_marker_roundtrip():
    text = "给你看 [VIDEO:/tmp/v.mp4|演示视频] 哦"
    cleaned, markers = extract_media_markers(text)
    assert "给你看" in cleaned
    assert markers == [{"kind": "video", "target": "/tmp/v.mp4", "name": "演示视频"}]
    assert MEDIA_MARKER_RE.search("[VIDEO:/tmp/v.mp4|演示视频]") is not None
