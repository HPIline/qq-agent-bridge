from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from silk_utils import encode_wav_to_silk

SendRecord = Callable[[str, str], Awaitable[None]]


class VoiceSender:
    """负责语音文本校验、TTS 合成、缓存与发送编排。"""

    def __init__(
        self,
        cfg: dict[str, Any],
        tts_client: Any,
        silk_encoder: Callable[[bytes], bytes] | None = None,
    ):
        self.cfg = cfg
        self.tts_client = tts_client
        self.silk_encoder = silk_encoder or encode_wav_to_silk
        cache_dir = Path(str(cfg.get("voice_cache_dir", "tmp/voice_cache")))
        if not cache_dir.is_absolute():
            cache_dir = Path(__file__).resolve().parent / cache_dir
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _cache_key(self, text: str) -> str:
        raw = f"{self.cfg.get('tts_character')}|{self.cfg.get('tts_ref')}|{text}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    async def prepare(self, text: str) -> Path:
        text = text.strip()
        if not text:
            raise ValueError("语音文本为空")
        max_chars = int(self.cfg.get("voice_max_chars", 120))
        if len(text) > max_chars:
            raise ValueError(f"语音文本过长（{len(text)} > {max_chars}）")
        target = self.cache_dir / f"{self._cache_key(text)}.wav"
        if target.exists() and target.stat().st_size > 0:
            return target
        async with self._lock:
            if target.exists() and target.stat().st_size > 0:
                return target
            data = await self.tts_client.synthesize(text)
            tmp = target.with_suffix(".tmp")
            await asyncio.to_thread(tmp.write_bytes, data)
            tmp.replace(target)
        return target

    async def send_voice(self, user_id: str, text: str, send_record: SendRecord) -> bool:
        try:
            path = await self.prepare(text)
            wav = await asyncio.to_thread(path.read_bytes)
            silk = await asyncio.to_thread(self.silk_encoder, wav)
            data = "base64://" + base64.b64encode(silk).decode("ascii")
            await send_record(user_id, data)
            return True
        except Exception as exc:
            logging.warning("语音发送失败：%s", exc)
            return False
