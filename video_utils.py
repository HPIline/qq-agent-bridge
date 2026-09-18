"""视频分析工具：ffmpeg 抽帧、音频提取与语音转写（whisper / mlx-whisper）、视频链接解析。

设计目标：
- 所有耗时操作放进 asyncio.to_thread，不阻塞事件循环；
- ffmpeg/ffprobe 优先从 config 指定路径找，其次 PATH，再其次 imageio-ffmpeg；
- 抽帧按视频时长均匀分布，限制最大宽度以控制视觉模型输入体积；
- 语音转写后端可配（video_asr_backend：auto / whisper / mlx-whisper / none），
  缺少依赖时安静降级为空文本，不影响其它功能。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from file_utils import download_file

BILIBILI_RE = re.compile(
    r"(https?://(?:www\.|m\.)?bilibili\.com/video/[A-Za-z0-9]+"
    r"|https?://b23\.tv/[A-Za-z0-9]+"
    r"|BV[0-9A-Za-z]{8,}"
    r"|\bav\d{2,}\b)",
    re.IGNORECASE,
)
DIRECT_VIDEO_RE = re.compile(
    r"https?://[^\s'\"]+\.(?:mp4|mov|m4v|webm|avi|mkv|flv)(?:\?[^\s'\"]*)?",
    re.IGNORECASE,
)


_FFMPEG_EXTRA_DIRS = (
    Path("/opt/homebrew/bin"),  # macOS Apple Silicon
    Path("/usr/local/bin"),  # macOS Intel
    Path("/usr/bin"),  # Linux
)


def _find_binary(cfg: dict[str, Any], key: str, name: str) -> str | None:
    """按 配置路径 → PATH → 常见安装目录 → imageio-ffmpeg 自带 的顺序查找。"""
    configured = str(cfg.get(key) or "").strip()
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which(name)
    if found:
        return found
    suffixes = ("", ".exe") if os.name == "nt" else ("",)
    for directory in _FFMPEG_EXTRA_DIRS + (Path(os.environ.get("QQBOT_BIN_DIR", "")),):
        if not str(directory):
            continue
        for suffix in suffixes:
            candidate = directory / f"{name}{suffix}"
            if candidate.is_file():
                return str(candidate)
    return None


def find_ffmpeg(cfg: dict[str, Any] | None = None) -> str | None:
    cfg = cfg or {}
    found = _find_binary(cfg, "video_ffmpeg_path", "ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).is_file():
            return path
    except Exception:
        pass
    return None


def find_ffprobe(cfg: dict[str, Any] | None = None) -> str | None:
    return _find_binary(cfg or {}, "video_ffprobe_path", "ffprobe")


async def probe_video(path: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """返回 {"duration": 秒, "width": int, "height": int}。

    优先 ffprobe；没有 ffprobe 时回退解析 ffmpeg -i 输出的 Duration。
    """
    ffprobe = find_ffprobe(cfg)
    if ffprobe:
        result = await asyncio.to_thread(_probe_with_ffprobe, ffprobe, path)
        if result.get("duration"):
            return result
    return await asyncio.to_thread(_probe_with_ffmpeg, find_ffmpeg(cfg), path)


def _probe_with_ffprobe(ffprobe: str, path: str) -> dict[str, Any]:
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        logging.warning("ffprobe 失败：%s", proc.stderr[-300:])
        return {"duration": 0.0, "width": 0, "height": 0}
    data = json.loads(proc.stdout or "{}")
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    width = height = 0
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video" and width == 0:
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            if stream.get("duration"):
                duration = max(duration, float(stream["duration"]))
            break
    return {"duration": duration, "width": width, "height": height}


def _probe_with_ffmpeg(ffmpeg: str | None, path: str) -> dict[str, Any]:
    if not ffmpeg:
        return {"duration": 0.0, "width": 0, "height": 0}
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    stderr = proc.stderr or ""
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    duration = 0.0
    if match:
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    width = height = 0
    vmatch = re.search(r"Video:.*?\s(\d{2,5})x(\d{2,5})[,\s]", stderr)
    if vmatch:
        width, height = int(vmatch.group(1)), int(vmatch.group(2))
    return {"duration": duration, "width": width, "height": height}


async def extract_frames(
    video_path: str,
    out_dir: str | Path,
    count: int = 8,
    max_width: int = 1280,
    cfg: dict[str, Any] | None = None,
) -> list[str]:
    """从视频中均匀抽取 count 帧，保存为 JPEG，返回路径列表。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(cfg)
    if not ffmpeg:
        raise RuntimeError(
            "未找到 ffmpeg，请先安装 ffmpeg（macOS: brew install ffmpeg / Windows: winget install ffmpeg），"
            "或在 config.json 里设置 video_ffmpeg_path"
        )
    count = max(1, int(count))
    info = await probe_video(video_path, cfg)
    duration = float(info.get("duration") or 0.0)
    if duration > 0:
        interval = max(duration / count, 0.1)
        fps_filter = f"fps={1.0 / interval:.6f}"
    else:
        fps_filter = "fps=1/1"
    pattern = out / "frame_%03d.jpg"

    def _run() -> list[str]:
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"{fps_filter},scale='min({max_width},iw)':-2",
            "-frames:v",
            str(count),
            "-q:v",
            "3",
            str(pattern),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 抽帧失败：{proc.stderr[-500:]}")
        frames = sorted(out.glob("frame_*.jpg"))
        return [str(p) for p in frames]

    return await asyncio.to_thread(_run)


async def build_videoshot_from_frames(
    frames: list[str],
    out_dir: str | Path,
    cols: int = 5,
    rows: int = 2,
    thumb_width: int = 160,
    thumb_height: int = 90,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把抽好的帧拼成 B 站 videoshot 接口形状的雪碧图。

    返回：
    {
      "image": [雪碧图本地路径, ...],   # 对应 B 站 data.image
      "index": [0, 秒, ...],            # 对应 B 站 data.index（读图顺序的时间表）
      "img_x_len": cols, "img_y_len": rows,
      "img_x_size": thumb_width, "img_y_size": thumb_height,
    }
    只借接口形状，不搬 B 站实现；帧按从左到右、从上到下排布。
    """
    frames = [str(f) for f in frames if Path(f).is_file()]
    if not frames:
        raise ValueError("没有可拼接的视频帧")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(cfg)
    if not ffmpeg:
        raise RuntimeError(
            "未找到 ffmpeg，请先安装 ffmpeg（macOS: brew install ffmpeg / Windows: winget install ffmpeg），"
            "或在 config.json 里设置 video_ffmpeg_path"
        )
    cols = max(1, int(cols))
    rows = max(1, int(rows))
    per_sheet = cols * rows
    sheet_paths: list[str] = []
    # 复制帧到统一编号目录，避免不同批次帧名冲突
    work = out / "frames"
    work.mkdir(parents=True, exist_ok=True)
    for i, frame in enumerate(frames):
        dest = work / f"frame_{i + 1:04d}.jpg"
        if Path(frame) != dest:
            dest.write_bytes(Path(frame).read_bytes())

    def _run() -> list[str]:
        produced: list[str] = []
        for start in range(0, len(frames), per_sheet):
            chunk_end = min(start + per_sheet, len(frames))
            chunk = list(range(start + 1, chunk_end + 1))
            if not chunk:
                break
            # 把当前 chunk 的帧复制为连续编号，便于 ffmpeg 按序读取
            chunk_dir = out / f"sheet_{start // per_sheet + 1:02d}"
            chunk_dir.mkdir(parents=True, exist_ok=True)
            for j, n in enumerate(chunk):
                src = work / f"frame_{n:04d}.jpg"
                dst = chunk_dir / f"frame_{j + 1:04d}.jpg"
                dst.write_bytes(src.read_bytes())
            sheet_name = f"sheet_{start // per_sheet + 1:02d}.jpg"
            sheet_path = out / sheet_name
            cmd = [
                ffmpeg,
                "-y",
                "-framerate",
                "1",
                "-i",
                str(chunk_dir / "frame_%04d.jpg"),
                "-vf",
                f"scale={int(thumb_width)}:{int(thumb_height)},tile={cols}x{rows}",
                "-q:v",
                "3",
                str(sheet_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg 拼雪碧图失败：{proc.stderr[-500:]}")
            if sheet_path.is_file():
                produced.append(str(sheet_path))
        return produced

    sheet_paths = await asyncio.to_thread(_run)
    return {
        "image": sheet_paths,
        "index": [0],
        "img_x_len": cols,
        "img_y_len": rows,
        "img_x_size": int(thumb_width),
        "img_y_size": int(thumb_height),
    }


def build_videoshot_index(duration: float, count: int) -> list[int]:
    """按均匀抽帧生成 B 站 videoshot 的 index 时间表（秒）。"""
    count = max(1, int(count))
    if count == 1:
        return [0]
    return [0] + [round(duration * i / count) for i in range(1, count)]


async def extract_audio(
    video_path: str,
    out_dir: str | Path,
    cfg: dict[str, Any] | None = None,
) -> str:
    """抽取 16kHz 单声道 wav，返回路径；没有音轨时返回空字符串。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(cfg)
    if not ffmpeg:
        raise RuntimeError(
            "未找到 ffmpeg，请先安装 ffmpeg（macOS: brew install ffmpeg / Windows: winget install ffmpeg），"
            "或在 config.json 里设置 video_ffmpeg_path"
        )
    wav_path = out / "audio.wav"

    def _run() -> str:
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            if (
                "does not contain any stream" in stderr
                or "Output file does not contain any stream" in stderr
            ):
                return ""
            raise RuntimeError(f"ffmpeg 抽音频失败：{stderr[-500:]}")
        return str(wav_path) if wav_path.is_file() else ""

    return await asyncio.to_thread(_run)


async def extract_subtitles(
    video_path: str,
    out_dir: str | Path,
    cfg: dict[str, Any] | None = None,
    max_chars: int = 4000,
) -> str:
    """从视频容器里导出第一条文本字幕轨，转成 SRT 文本返回。

    没有字幕轨、字幕是位图（如 PGS）或转换失败时返回空字符串。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(cfg)
    if not ffmpeg:
        return ""

    def _run() -> str:
        srt_path = out / "subtitle.srt"
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-map",
            "0:s:0",
            "-c:s",
            "srt",
            str(srt_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not srt_path.is_file():
            return ""
        text = srt_path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return ""
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n（字幕内容过长，已截断）"
        return text

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:
        logging.warning("字幕导出失败：%s", exc)
        return ""


def cleanup_video_cache(tmp_dir: str | Path, max_age_sec: int = 86400) -> int:
    """清理过期的视频抽帧目录，返回删除的目录数。

    只清理 tmp/video_frames 下的旧目录；视频文件本体在每次分析完成后即时删除。
    """
    root = Path(tmp_dir) / "video_frames"
    if not root.exists():
        return 0
    removed = 0
    now = time.time()
    for child in root.iterdir():
        try:
            if not child.is_dir():
                continue
            if now - child.stat().st_mtime > max_age_sec:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except Exception as exc:
            logging.warning("清理视频缓存失败：%s %s", child, exc)
    return removed


def _transcribe_mlx(audio_path: str, model: str, language: str | None) -> str:
    import mlx_whisper  # type: ignore

    kwargs: dict[str, Any] = {"path_or_hf_repo": model, "verbose": False}
    if language:
        kwargs["language"] = language
    try:
        result = mlx_whisper.transcribe(audio_path, **kwargs)
    except TypeError:
        result = mlx_whisper.transcribe(audio_path, path_or_hf_repo=model, verbose=False)
    return str((result or {}).get("text") or "").strip()


def _transcribe_whisper(audio_path: str, model: str, language: str | None) -> str:
    """openai-whisper（跨平台，CPU/GPU 都能跑）。"""
    import whisper  # type: ignore

    name = model.split("/")[-1] if "/" in model else model
    name = name.replace("whisper-", "")
    loaded = whisper.load_model(name)
    result = loaded.transcribe(audio_path, language=language or None, verbose=False)
    return str((result or {}).get("text") or "").strip()


def _transcribe_faster_whisper(audio_path: str, model: str, language: str | None) -> str:
    """faster-whisper（CTranslate2 后端，速度更快）。"""
    from faster_whisper import WhisperModel  # type: ignore

    name = model.split("/")[-1] if "/" in model else model
    name = name.replace("whisper-", "")
    if name in ("turbo", "large-v3-turbo"):
        name = "large-v3"
    loaded = WhisperModel(name, device="auto", compute_type="auto")
    segments, _info = loaded.transcribe(audio_path, language=language or None)
    return "".join(segment.text for segment in segments).strip()


def _transcribe_backends(backend: str) -> list[str]:
    backend_name = str(backend or "auto").strip().lower()
    if backend_name in ("none", "off", "disabled", ""):
        return []
    if backend_name not in ("auto",):
        return [backend_name]
    order: list[str] = []
    if sys.platform == "darwin":
        order.append("mlx-whisper")
    order.extend(["whisper", "faster-whisper"])
    return order


async def transcribe_audio(
    audio_path: str,
    model: str = "whisper-turbo",
    language: str | None = None,
    timeout: int = 600,
    backend: str = "auto",
) -> str:
    """转写音频，返回纯文本；缺依赖或失败时返回空字符串（不抛错）。"""
    backends = _transcribe_backends(backend)
    if not backends:
        return ""

    def _run() -> str:
        proxy_keys = [
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ]
        saved = {key: os.environ.pop(key, None) for key in proxy_keys}
        try:
            for name in backends:
                try:
                    if name in ("mlx", "mlx-whisper"):
                        return _transcribe_mlx(audio_path, model, language)
                    if name in ("whisper", "openai-whisper"):
                        return _transcribe_whisper(audio_path, model, language)
                    if name in ("faster-whisper", "faster_whisper"):
                        return _transcribe_faster_whisper(audio_path, model, language)
                    logging.warning("未知的语音转写后端：%s", name)
                except ImportError:
                    logging.warning("%s 未安装，尝试下一个转写后端", name)
                except Exception as exc:  # noqa: BLE001
                    logging.warning("%s 转写失败：%s", name, exc)
            return ""
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
    except TimeoutError:
        logging.warning("音频转写超时（%s 秒）", timeout)
        return ""
    except Exception as exc:
        logging.warning("音频转写失败：%s", exc)
        return ""


def extract_video_links(text: str) -> list[str]:
    """从文本里提取视频链接/编号。返回原始链接或 BV/av 号。"""
    hits: list[str] = []
    for match in BILIBILI_RE.finditer(text or ""):
        hits.append(match.group(0))
    for match in DIRECT_VIDEO_RE.finditer(text or ""):
        hits.append(match.group(0))
    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for hit in hits:
        key = hit.strip().rstrip(".,，。；;")
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


async def download_video_from_link(
    link: str,
    dest_dir: str | Path,
    cfg: dict[str, Any] | None = None,
) -> str:
    """下载直链或 B 站视频，返回本地路径。"""
    return (await download_video_from_link_with_subtitles(link, dest_dir, cfg))[0]


async def download_video_from_link_with_subtitles(
    link: str,
    dest_dir: str | Path,
    cfg: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """下载直链或 B 站视频，返回 (本地路径, 字幕文本)。

    直链没有配套字幕文件时字幕文本为空字符串；B 站链接会尝试读取
    yt-dlp 抓取的 SRT 字幕。
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if DIRECT_VIDEO_RE.match(link.strip()):
        name = Path(link.split("?")[0]).name or "video.mp4"
        path = await download_file(link.strip(), dest, name)
        return path, ""
    # B 站：优先 yt-dlp
    try:
        path = await _download_bilibili(link.strip(), dest, cfg)
        max_chars = int((cfg or {}).get("video_subtitle_max_chars", 4000))
        subtitle_text = _read_subtitle_files(dest, Path(path).stem, max_chars)
        return path, subtitle_text
    except Exception as exc:
        raise RuntimeError(
            f"B 站视频下载失败：{exc}（提示：需要安装 yt-dlp，pip install yt-dlp）"
        ) from exc


def _read_subtitle_files(dest_dir: Path, stem: str, max_chars: int) -> str:
    """读取 yt-dlp 写在视频旁边的 SRT 字幕，拼成一段文本。"""
    candidates = sorted(dest_dir.glob(f"{stem}*.srt"))
    if not candidates:
        candidates = sorted(dest_dir.glob("*.srt"))
    texts: list[str] = []
    for subtitle_file in candidates[:3]:
        try:
            content = subtitle_file.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                texts.append(f"[{subtitle_file.name}]\n{content}")
        except Exception:
            continue
    joined = "\n\n".join(texts)
    if len(joined) > max_chars:
        joined = joined[:max_chars].rstrip() + "\n（字幕内容过长，已截断）"
    return joined


async def _download_bilibili(
    ref: str,
    dest_dir: Path,
    cfg: dict[str, Any] | None = None,
) -> str:
    url = ref
    if not ref.startswith("http"):
        if ref.lower().startswith("bv"):
            url = f"https://www.bilibili.com/video/{ref}"
        elif ref.lower().startswith("av"):
            url = f"https://www.bilibili.com/video/{ref}"
        else:
            url = f"https://www.bilibili.com/video/{ref}"
    quality = str((cfg or {}).get("video_bilibili_quality", "480"))

    def _run() -> str:
        try:
            import yt_dlp  # type: ignore
        except Exception as exc:
            raise RuntimeError("yt-dlp 未安装") from exc
        outtmpl = str(dest_dir / "%(id)s.%(ext)s")
        fmt = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
        opts = {
            "outtmpl": outtmpl,
            "format": fmt,
            "merge_output_format": "mp4",
            "quiet": True,
            "noprogress": True,
            "proxy": "__noproxy__",
            # 顺手抓 B 站字幕（CC 字幕 / AI 字幕），统一转成 SRT 写在视频旁边
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hans", "zh-CN", "zh", "ja", "en"],
            "subtitlesformat": "srt",
        }
        ffmpeg = find_ffmpeg(cfg)
        if ffmpeg:
            # LaunchAgent 的 PATH 受限，yt-dlp 找不到 Homebrew 的 ffmpeg，
            # 这里把绝对路径所在目录显式告诉它。
            opts["ffmpeg_location"] = str(Path(ffmpeg).parent)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("yt-dlp 返回空信息")
            filepath = ydl.prepare_filename(info)
            if not Path(filepath).exists():
                # 合并后的扩展名可能是 mp4
                candidates = sorted(dest_dir.glob(f"{info.get('id') or '*'}.mp4"))
                if candidates:
                    return str(candidates[-1])
            return str(filepath)

    return await asyncio.to_thread(_run)
