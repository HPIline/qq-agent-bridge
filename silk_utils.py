from __future__ import annotations

import io
import os
import tempfile
import wave
from pathlib import Path


def encode_wav_to_silk(wav_bytes: bytes) -> bytes:
    """把单声道 16bit WAV 转成 Tencent SILK 字节（QQ 语音格式）。"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    if channels != 1 or width != 2:
        raise ValueError(f"仅支持单声道 16bit WAV，当前 {channels}ch/{width * 8}bit")
    fd_pcm, pcm_path = tempfile.mkstemp(suffix=".pcm")
    fd_silk, silk_path = tempfile.mkstemp(suffix=".silk")
    os.close(fd_silk)
    try:
        with os.fdopen(fd_pcm, "wb") as f:
            f.write(frames)
        import pilk

        encoder = pilk.SilkEncoder(pcm_rate=rate, silk_rate=24000, max_rate=24000)
        encoder.encode(pcm_path, silk_path, tencent=True)
        return Path(silk_path).read_bytes()
    finally:
        for path in (pcm_path, silk_path):
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
