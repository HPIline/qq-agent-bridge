"""video_utils 测试：链接提取、videoshot 接口形状、抽帧与探测。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import pytest

from video_utils import (
    build_videoshot_from_frames,
    build_videoshot_index,
    cleanup_video_cache,
    extract_frames,
    extract_subtitles,
    extract_video_links,
    find_ffmpeg,
    probe_video,
)


@pytest.fixture(scope="module")
def ffmpeg() -> str:
    path = find_ffmpeg({})
    if not path:
        pytest.skip("没有可用的 ffmpeg")
    return path


@pytest.fixture()
def sample_video(tmp_path: Path, ffmpeg: str) -> Path:
    video = tmp_path / "sample.mp4"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=6:size=320x240:rate=10",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    return video


def test_extract_video_links():
    text = (
        "看看这个 https://example.com/a.mp4?x=1 和 "
        "https://b23.tv/abc123 还有 BV1xx411c7mD 和 av170001"
    )
    hits = extract_video_links(text)
    assert "https://example.com/a.mp4?x=1" in hits
    assert "https://b23.tv/abc123" in hits
    assert "BV1xx411c7mD" in hits
    assert "av170001" in hits


def test_build_videoshot_index():
    assert build_videoshot_index(0, 1) == [0]
    assert build_videoshot_index(6, 3) == [0, 2, 4]
    assert build_videoshot_index(10, 5) == [0, 2, 4, 6, 8]


def test_probe_video(sample_video: Path):
    info = asyncio.run(probe_video(str(sample_video)))
    assert 5.0 <= info["duration"] <= 7.0
    assert info["width"] == 320
    assert info["height"] == 240


def test_extract_frames(sample_video: Path, tmp_path: Path):
    frames = asyncio.run(extract_frames(str(sample_video), tmp_path, count=5))
    assert len(frames) == 5
    assert all(Path(p).is_file() for p in frames)


def test_build_videoshot_from_frames_borrows_bilibili_shape(sample_video: Path, tmp_path: Path):
    frames = asyncio.run(extract_frames(str(sample_video), tmp_path / "frames", count=5))
    shot = asyncio.run(
        build_videoshot_from_frames(
            frames,
            tmp_path / "shot",
            cols=3,
            rows=2,
            thumb_width=160,
            thumb_height=90,
        )
    )
    # 只借接口形状：与 bilibili-API-collect 的 videoshot 字段一致
    assert set(shot) == {"image", "index", "img_x_len", "img_y_len", "img_x_size", "img_y_size"}
    assert shot["img_x_len"] == 3
    assert shot["img_y_len"] == 2
    assert shot["img_x_size"] == 160
    assert shot["img_y_size"] == 90
    assert shot["index"] == [0]
    assert len(shot["image"]) >= 1
    assert all(Path(p).is_file() for p in shot["image"])


def test_extract_subtitles(tmp_path: Path, ffmpeg: str):
    srt = tmp_path / "sub.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好世界\n",
        encoding="utf-8",
    )
    video = tmp_path / "with_sub.mp4"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x90:d=2",
            "-i",
            str(srt),
            "-c:v",
            "libx264",
            "-c:s",
            "mov_text",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    text = asyncio.run(extract_subtitles(str(video), tmp_path / "out"))
    assert "你好世界" in text


def test_extract_subtitles_returns_empty_for_video_without_subtitle(
    sample_video: Path, tmp_path: Path
):
    text = asyncio.run(extract_subtitles(str(sample_video), tmp_path / "out2"))
    assert text == ""


def test_cleanup_video_cache(tmp_path: Path):
    root = tmp_path / "video_frames"
    old_dir = root / "old"
    new_dir = root / "new"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old_ts = time.time() - 7200
    os.utime(old_dir, (old_ts, old_ts))
    removed = cleanup_video_cache(tmp_path, max_age_sec=3600)
    assert removed == 1
    assert not old_dir.exists()
    assert new_dir.exists()
