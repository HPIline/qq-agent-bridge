"""视频分析流程集成测试（抽帧/雪碧图/转写为假实现，只验证拼装逻辑与清理）。"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

import handlers
from video_utils import find_ffmpeg


class FakeBridge:
    def __init__(self, tmp_path: Path):
        self.tmp_dir = tmp_path
        self.cfg = {
            "video_max_frames": 4,
            "video_max_width": 640,
            "video_asr_enabled": True,
            "video_asr_model": "mlx-community/whisper-turbo",
            "video_asr_language": "",
            "video_asr_timeout": 60,
            "video_subtitle_enabled": True,
            "video_subtitle_max_chars": 4000,
            "video_asr_skip_if_subtitles": True,
            "mimo_vision_url": "http://fake",
            "mimo_vision_model": "mimo-v2.5",
            "mimo_vision_api_key": "",
            "vision_timeout_sec": 30,
            "mimo_vision_max_tokens": 800,
            "video_shot_cols": 3,
            "video_shot_rows": 2,
            "video_shot_thumb_width": 120,
            "video_shot_thumb_height": 68,
        }


@pytest.fixture()
def sample_video(tmp_path: Path) -> Path:
    ffmpeg = find_ffmpeg({})
    if not ffmpeg:
        pytest.skip("没有可用的 ffmpeg")
    video = tmp_path / "sample.mp4"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=320x240:rate=10",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    return video


def test_analyze_video_path_assembles_prompt_and_cleans_up(
    monkeypatch, tmp_path: Path, sample_video: Path
):
    async def fake_describe_image(
        image_path, api_url, model, api_key=None, timeout=150, max_tokens=1200, prompt=None
    ):
        return f"画面描述：{Path(image_path).name}"

    async def fake_extract_audio(video_path, out_dir, cfg=None):
        return str(Path(out_dir) / "audio.wav")

    async def fake_transcribe_audio(
        audio_path, model="", language=None, timeout=600, backend="auto"
    ):
        return "这是测试音频转写"

    monkeypatch.setattr(handlers, "describe_image", fake_describe_image)
    monkeypatch.setattr(handlers, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(handlers, "transcribe_audio", fake_transcribe_audio)

    bridge = FakeBridge(tmp_path)
    text = asyncio.run(handlers._analyze_video_path(bridge, str(sample_video), "测试视频"))
    assert "视频文件：测试视频" in text
    assert "时长：约 4 秒" in text
    assert "字幕：（无字幕轨或导出失败）" in text
    assert "音频转写：\n这是测试音频转写" in text
    assert "抽帧画面描述：" in text
    assert "画面描述：frame_" in text
    assert "帧时间表（秒，videoshot.index）：[0, 1, 2, 3]" in text
    # 处理完即删：视频本体与抽帧目录都不应残留
    assert not sample_video.exists()
    assert not (tmp_path / "video_frames").exists() or not any(
        (tmp_path / "video_frames").iterdir()
    )
