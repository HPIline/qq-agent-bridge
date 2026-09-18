"""媒体发送与接收：文件/图片/表情/语音、入站文件下载。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from file_utils import download_file, safe_filename, save_base64_data
from vision_client import download_image


def _is_http_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value, re.IGNORECASE))


def _local_path_from_url(value: str) -> str | None:
    """把 file:// 或普通本地路径规范化为可检查的本地路径。"""
    if not value:
        return None
    if value.startswith("file://"):
        return unquote(urlparse(value).path) or None
    return value


async def call_action(
    bridge: Any, action: str, params: dict[str, Any], timeout: float = 60.0
) -> dict[str, Any]:
    if bridge.ws is None:
        raise ConnectionError("WebSocket 未连接")
    echo = f"bridge-{uuid.uuid4().hex}"
    fut = asyncio.get_running_loop().create_future()
    bridge.pending_actions[echo] = fut
    try:
        await bridge.ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
        response = await asyncio.wait_for(fut, timeout)
    finally:
        bridge.pending_actions.pop(echo, None)
    if response.get("status") == "failed":
        message = response.get("message") or response.get("wording") or ""
        raise RuntimeError(f"{action} 失败：{message}")
    return response.get("data") or {}


async def send_private_file(bridge: Any, user_id: str, target: str, name: str) -> None:
    try:
        user_id_num = int(user_id)
    except ValueError:
        user_id_num = user_id
    if not name.strip():
        name = Path(target.split("?")[0]).name or "file"
    if re.match(r"^https?://", target, re.IGNORECASE):
        upload_target = target
    else:
        source = Path(target)
        if not source.is_file():
            raise FileNotFoundError(f"文件不存在：{source}")
        raw = await asyncio.to_thread(source.read_bytes)
        upload_target = "base64://" + base64.b64encode(raw).decode("ascii")
    await bridge._call_action(
        "upload_private_file",
        {"user_id": user_id_num, "file": upload_target, "name": name},
        timeout=120,
    )
    logging.info("文件已发送给 %s：%s（%s）", user_id, name, target)


async def send_private_segments(bridge: Any, user_id: str, segments: list[dict[str, Any]]) -> None:
    if bridge.ws is None:
        raise ConnectionError("WebSocket 未连接")
    try:
        user_id_num = int(user_id)
    except ValueError:
        user_id_num = user_id
    payload = {
        "action": "send_private_msg",
        "params": {"user_id": user_id_num, "message": segments},
    }
    await bridge.ws.send(json.dumps(payload, ensure_ascii=False))
    logging.info("已发送给 %s：%s", user_id, segments[0]["type"])


async def send_private_face(bridge: Any, user_id: str, face_id: str) -> None:
    await send_private_segments(bridge, user_id, [{"type": "face", "data": {"id": str(face_id)}}])


async def send_private_mface(bridge: Any, user_id: str, marker: dict[str, str]) -> None:
    data = {
        "emoji_id": marker.get("emoji_id", ""),
        "emoji_package_id": marker.get("emoji_package_id", ""),
        "key": marker.get("key", ""),
        "summary": marker.get("summary", ""),
    }
    data = {k: v for k, v in data.items() if v}
    await send_private_segments(bridge, user_id, [{"type": "mface", "data": data}])


async def send_private_image(bridge: Any, user_id: str, target: str, name: str = "") -> None:
    if re.match(r"^https?://", target, re.IGNORECASE):
        upload_target = target
    else:
        source = Path(target)
        if not source.is_file():
            raise FileNotFoundError(f"图片不存在：{source}")
        raw = await asyncio.to_thread(source.read_bytes)
        upload_target = "base64://" + base64.b64encode(raw).decode("ascii")
    await send_private_segments(
        bridge, user_id, [{"type": "image", "data": {"file": upload_target}}]
    )
    logging.info("图片已发送给 %s：%s", user_id, name or target)


async def send_private_video(bridge: Any, user_id: str, target: str, name: str = "") -> None:
    if re.match(r"^https?://", target, re.IGNORECASE):
        upload_target = target
    else:
        source = Path(target)
        if not source.is_file():
            raise FileNotFoundError(f"视频不存在：{source}")
        raw = await asyncio.to_thread(source.read_bytes)
        upload_target = "base64://" + base64.b64encode(raw).decode("ascii")
    await send_private_segments(
        bridge,
        user_id,
        [
            {
                "type": "video",
                "data": {"file": upload_target, "name": name or Path(target.split("?")[0]).name},
            }
        ],
    )
    logging.info("视频已发送给 %s：%s", user_id, name or target)


async def send_private_record(bridge: Any, user_id: str, path: str) -> None:
    try:
        user_id_num = int(user_id)
    except ValueError:
        user_id_num = user_id
    await bridge._call_action(
        "send_private_msg",
        {
            "user_id": user_id_num,
            "message": [{"type": "record", "data": {"file": path}}],
        },
        timeout=60,
    )
    logging.info("语音已发送给 %s", user_id)


async def send_media_marker(bridge: Any, user_id: str, marker: dict[str, str]) -> None:
    kind = marker["kind"]
    if kind == "face":
        await send_private_face(bridge, user_id, marker["id"])
    elif kind == "mface":
        await send_private_mface(bridge, user_id, marker)
    elif kind == "image":
        await send_private_image(bridge, user_id, marker["target"], marker["name"])
    elif kind == "video":
        await send_private_video(bridge, user_id, marker["target"], marker["name"])
    elif kind == "file":
        await send_private_file(bridge, user_id, marker["target"], marker["name"])
    else:
        raise ValueError(f"未知标记：{kind}")


async def download_incoming_image(bridge: Any, image: dict[str, str]) -> str:
    url = str(image.get("url") or "")
    file_ref = str(image.get("file") or "")
    data: dict[str, Any] = {}
    if file_ref or url:
        try:
            data = await bridge._call_action("get_image", {"file": file_ref or url}, timeout=60)
        except Exception as exc:
            logging.warning("get_image 失败，改用 URL 下载：%s", exc)
    local_path = str(data.get("file") or data.get("path") or "")
    if local_path and Path(local_path).is_file():
        logging.info("get_image 返回本地文件：%s", local_path)
        return local_path
    fresh_url = str(data.get("url") or "")
    if fresh_url:
        try:
            return await download_image(fresh_url, bridge.tmp_dir)
        except Exception as exc:
            logging.warning("get_image 返回的 URL 下载失败，退回事件 URL：%s", exc)
    if url:
        return await download_image(url, bridge.tmp_dir)
    raise RuntimeError("图片消息缺少 url 和 file 字段")


async def download_incoming_video(bridge: Any, video: dict[str, str]) -> str:
    """下载/定位收到的视频文件，返回本地绝对路径。

    NapCat 的 OneBot v11 video 段 data 字段：file（路径/URL/file:///）、
    path（本地路径）、url（下载地址）、name（文件名）。按优先级依次尝试。
    """
    url = str(video.get("url") or "")
    file_ref = str(video.get("file") or "")
    path = str(video.get("path") or "")
    name = str(video.get("name") or "")
    if file_ref.startswith("file:"):
        # 跨平台解析 file:/// URL（Windows 下 file:///C:/x → C:\\x）
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        parsed = urlparse(file_ref)
        local_path = url2pathname(parsed.path)
        if parsed.netloc:
            local_path = f"//{parsed.netloc}{local_path}"
        file_ref = local_path
    for candidate in (url, file_ref):
        if _is_http_url(candidate):
            return await download_file(candidate, bridge.incoming_dir, name or "video.mp4")
    for candidate in (path, file_ref, url):
        if candidate and Path(candidate).is_file():
            return await copy_local_media(bridge, candidate, name or Path(candidate).name)
    if url:
        return await download_file(url, bridge.incoming_dir, name or "video.mp4")
    if file_ref:
        try:
            data = await bridge._call_action("get_file", {"file_id": file_ref}, timeout=60)
            url = str(data.get("url") or "")
            if url:
                return await download_file(
                    url, bridge.incoming_dir, name or str(data.get("file_name") or "video.mp4")
                )
            local_path = str(data.get("file") or data.get("path") or "")
            if local_path and Path(local_path).is_file():
                return await copy_local_media(bridge, local_path, name or Path(local_path).name)
            b64 = str(data.get("base64") or data.get("data") or "")
            if b64:
                return await save_base64_data(b64, bridge.incoming_dir, name or "video.mp4")
        except Exception as exc:
            logging.warning("get_file 获取视频失败：%s", exc)
    raise FileNotFoundError("视频消息缺少可下载的 url/file/path")


async def copy_local_media(bridge: Any, local_path: str, name: str) -> str:
    source = Path(local_path)
    if not source.is_file():
        raise FileNotFoundError(f"本地媒体文件不存在：{source}")
    dest = bridge.incoming_dir / safe_filename(name or source.name, fallback="video.mp4")
    counter = 1
    candidate = dest
    while candidate.exists():
        candidate = dest.with_name(f"{dest.stem}_{counter}{dest.suffix}")
        counter += 1
    await asyncio.to_thread(shutil.copy2, source, candidate)
    return str(candidate)


async def _copy_local_file(bridge: Any, local_path: str, name: str = "") -> str:
    """把本地文件复制到 incoming 目录并返回路径。"""
    dest = bridge.incoming_dir / safe_filename(name or Path(local_path).name, fallback="file")
    counter = 1
    candidate = dest
    while candidate.exists():
        candidate = dest.with_name(f"{dest.stem}_{counter}{dest.suffix}")
        counter += 1
    await asyncio.to_thread(shutil.copy2, local_path, candidate)
    return str(candidate)


async def _download_or_copy(bridge: Any, url: str, name: str = "") -> str:
    """http(s) 走下载；file:// 或本地路径走复制。"""
    if _is_http_url(url):
        return await download_file(url, bridge.incoming_dir, name)
    local_path = _local_path_from_url(url)
    if local_path and Path(local_path).is_file():
        return await _copy_local_file(bridge, local_path, name or Path(local_path).name)
    raise FileNotFoundError(f"URL 不可下载：{url}")


async def download_incoming_file(bridge: Any, file: dict[str, str]) -> str:
    url = file.get("url") or ""
    name = file.get("name") or ""
    file_id = file.get("file_id") or file.get("file") or ""
    if url:
        return await _download_or_copy(bridge, url, name)
    if file_id:
        try:
            data = await bridge._call_action(
                "get_private_file_url", {"file_id": file_id}, timeout=60
            )
            url = str(data.get("url") or "")
            if url:
                return await _download_or_copy(bridge, url, name or str(data.get("name") or ""))
        except Exception:
            pass
        try:
            data = await bridge._call_action("get_file", {"file_id": file_id}, timeout=60)
        except Exception as exc:
            raise FileNotFoundError(f"无法获取文件：{exc}") from exc
        logging.info(
            "get_file 响应：file=%s file_name=%s url=%s base64=%s",
            data.get("file"),
            data.get("file_name"),
            bool(data.get("url")),
            bool(data.get("base64") or data.get("data")),
        )
        url = str(data.get("url") or "")
        if url:
            try:
                return await _download_or_copy(
                    bridge, url, name or str(data.get("file_name") or "")
                )
            except FileNotFoundError:
                # NapCat 偶发把本地路径塞进 url 字段；继续尝试 file / base64 字段
                pass
        local_path = str(data.get("file") or data.get("path") or "")
        if local_path and Path(local_path).is_file():
            return await _copy_local_file(bridge, local_path, name or Path(local_path).name)
        b64 = str(data.get("base64") or data.get("data") or "")
        if b64:
            return await save_base64_data(b64, bridge.incoming_dir, name)
        raise FileNotFoundError("get_file 未返回可用的文件")
    raise FileNotFoundError("文件消息缺少 file_id 和 url")
