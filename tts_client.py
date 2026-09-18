from __future__ import annotations

import asyncio
import base64
import json
import logging
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


def load_characters(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"characters.json 不存在：{p}")
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("characters.json 格式错误：应为数组")
    return data


def find_character(characters: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for char in characters:
        if char.get("name") == name:
            return char
    return None


def find_ref(character: dict[str, Any], ref_name: str) -> dict[str, Any] | None:
    for ref in character.get("refs", []):
        if ref.get("name") == ref_name:
            return ref
    return None


class LocalGPTSoVITSClient:
    """调用本地 GPT-SoVITS api_v2 服务合成语音。"""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.timeout = int(cfg.get("tts_timeout_sec", 120))
        url = str(cfg.get("tts_local_url", "http://127.0.0.1:9880/tts"))
        base = url
        for suffix in ("/tts", "/"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        self._base = base
        self._characters: list[dict[str, Any]] | None = None
        self._loaded_weights: tuple[str, str] | None = None

    def characters(self) -> list[dict[str, Any]]:
        if self._characters is None:
            path = Path(self.cfg["tts_models_dir"]) / "GPT_weights_v2" / "characters.json"
            self._characters = load_characters(path)
        return self._characters

    async def _get(self, path: str, params: dict[str, str]) -> None:
        url = f"{self._base}{path}?{urlencode(params)}"

        def _call() -> None:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()

        await asyncio.to_thread(_call)

    async def _ensure_weights(self, char: dict[str, Any]) -> None:
        models_dir = Path(self.cfg["tts_models_dir"])
        gpt_path = str(models_dir / char["gpt"])
        sovits_path = str(models_dir / char["sovits"])
        if self._loaded_weights == (gpt_path, sovits_path):
            return
        await self._get("/set_gpt_weights", {"weights_path": gpt_path})
        await self._get("/set_sovits_weights", {"weights_path": sovits_path})
        self._loaded_weights = (gpt_path, sovits_path)

    async def synthesize(self, text: str) -> bytes:
        char = find_character(self.characters(), self.cfg["tts_character"])
        if char is None:
            raise RuntimeError(f"characters.json 中找不到角色：{self.cfg['tts_character']}")
        ref = find_ref(char, self.cfg["tts_ref"])
        if ref is None:
            raise RuntimeError(f"角色 {char['name']} 中找不到预设语气：{self.cfg['tts_ref']}")
        await self._ensure_weights(char)
        models_dir = Path(self.cfg["tts_models_dir"])
        # 参考音频所在子目录可在配置里改（不同语音包目录结构可能不同）
        ref_dir = str(self.cfg.get("tts_ref_dir") or "").strip()
        ref_path = models_dir / ref_dir / ref["file"] if ref_dir else models_dir / ref["file"]
        if not ref_path.is_file():
            raise FileNotFoundError(f"参考音频不存在：{ref_path}")
        payload = {
            "text": text,
            "text_lang": self.cfg.get("tts_text_lang", "all_ja"),
            "ref_audio_path": str(ref_path),
            "prompt_text": ref["text"],
            "prompt_lang": self.cfg.get("tts_prompt_lang", "all_ja"),
            "top_k": 15,
            "top_p": 1.0,
            "temperature": 1.0,
            "text_split_method": "cut5",
            "batch_size": 1,
            "speed_factor": 1.0,
            "stream": False,
        }
        url = self.cfg["tts_local_url"]

        def _call() -> bytes:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                ctype = resp.headers.get("Content-Type", "")
                body = resp.read()
            if "json" in ctype or body[:1] in (b"{", b"["):
                data = json.loads(body.decode("utf-8", errors="replace"))
                if isinstance(data, dict) and data.get("code") not in (0, None):
                    raise RuntimeError(f"TTS 错误：{data}")
                audio = data.get("data") if isinstance(data, dict) else None
                if isinstance(audio, dict):
                    audio = audio.get("audio") or audio.get("data") or ""
                if isinstance(audio, str):
                    if audio.startswith("data:"):
                        audio = audio.split(",", 1)[1]
                    if audio:
                        return base64.b64decode(audio)
                raise RuntimeError(f"TTS 返回 JSON 未包含音频：{data}")
            if not body:
                raise RuntimeError("TTS 返回空音频")
            return body

        wav = await asyncio.to_thread(_call)
        logging.info("TTS 合成完成：%d 字节", len(wav))
        return wav
