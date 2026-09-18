# 视频理解与 AstrBot 兼容层

## 1. 看视频功能

私聊直接给机器人发视频，桥接会自动下载、抽帧、逐帧视觉描述、音频转写，然后把结果交给核心模型回答。也支持在文字里附带视频链接（直链 mp4/mov/m4v/webm 等，以及 B 站 BV/av/b23 链接）。

### 1.1 处理流程

```text
QQ 视频消息 / 视频链接
    │
下载到 tmp/incoming
    │
ffprobe 探测时长/分辨率（无 ffprobe 时回退解析 ffmpeg -i 输出）
    │
ffmpeg 导出第一条文本字幕轨为 SRT（可选，有字幕则优先用于理解）
    │
ffmpeg 均匀抽取 N 帧（默认 8 帧，最大宽 1280）
    │
视觉模型逐帧描述画面（复用 vision_client）
    │
ffmpeg 抽 16kHz 单声道 wav → 语音转写（video_asr_backend 可选 whisper / faster-whisper / mlx-whisper；
有字幕且 video_asr_skip_if_subtitles=true 时跳过）
    │
生成 B 站 videoshot 形状的进度条雪碧图（见 1.3）
    │
拼接成“视频分析”文本块，交给核心模型汇总回答
    │
清理：删除本视频文件与抽帧目录（处理完即删）
```

### 1.2 配置项

所有配置都有默认值，不写进 `config.json` 也会生效：

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `video_analysis_enabled` | `true` | 收到视频消息是否自动分析 |
| `video_max_frames` | `8` | 每个视频抽多少帧 |
| `video_max_width` | `1280` | 抽帧最大宽度 |
| `video_asr_enabled` | `true` | 是否做音频转写 |
| `video_asr_model` | `mlx-community/whisper-turbo` | mlx-whisper 模型 |
| `video_asr_language` | `""` | 转写语言，空为自动检测 |
| `video_asr_timeout` | `600` | 转写超时秒数 |
| `video_subtitle_enabled` | `true` | 是否从容器导出第一条文本字幕轨 |
| `video_subtitle_max_chars` | `4000` | 字幕内容最大字符数 |
| `video_asr_skip_if_subtitles` | `true` | 有字幕时跳过音频转写 |
| `video_link_parse_enabled` | `true` | 是否自动识别并下载文字里的视频链接 |
| `video_bilibili_quality` | `480` | B 站下载清晰度上限（yt-dlp format） |
| `video_ffmpeg_path` / `video_ffprobe_path` | `""` | 自定义 ffmpeg/ffprobe 路径；留空自动找 PATH、Homebrew 或 imageio-ffmpeg |
| `video_shot_cols` / `video_shot_rows` | `5` / `2` | 雪碧图每张拼版的列数/行数 |
| `video_shot_thumb_width` / `video_shot_thumb_height` | `160` / `90` | 雪碧图缩略图尺寸 |

### 1.3 进度条预览雪碧图（videoshot 形状）

只借 [bilibili-API-collect 的 videoshot 接口形状](https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/video/snapshot.md)，不搬 B 站实现。

`video_utils.build_videoshot_from_frames(frames, out_dir, ...)` 返回：

```json
{
  "image": ["/绝对路径/sheet_01.jpg", "/绝对路径/sheet_02.jpg"],
  "index": [0],
  "img_x_len": 5,
  "img_y_len": 2,
  "img_x_size": 160,
  "img_y_size": 90
}
```

字段含义与 B 站 `data` 对象一致：`image` 是雪碧图拼版数组，`index` 是每帧对应的秒数时间表（`video_utils.build_videoshot_index(duration, count)` 生成）。帧按从左到右、从上到下排布。

### 1.4 依赖

```bash
brew install ffmpeg            # 或使用 imageio-ffmpeg 自带二进制（requirements 已包含）
.venv/bin/pip install -r requirements.txt
```

- `imageio-ffmpeg`：自带 ffmpeg 二进制（无 ffprobe，时长回退解析 ffmpeg 输出）。
- `mlx-whisper`：Apple Silicon 本地语音转写，首次使用会从 HuggingFace 下载模型。
- `yt-dlp`：B 站链接下载（直链下载不依赖它）。

缓存策略：每个视频分析完成后，会立即删除下载的视频本体和抽帧/音频/雪碧图目录；
`tmp/video_frames` 下超过 24 小时的残留目录会在下次分析时顺手清理。

## 2. AstrBot 兼容层

qq-agent-bridge 内置了一个轻量 `astrbot` 包（本地 shim，不使用 PyPI 的 astrbot），让生态里只依赖 `astrbot.api` 的简单插件可以直接运行。

### 2.1 安装插件

把插件目录放进 `qq-agent-bridge/astrbot_plugins/`，重启桥接即可。插件目录必须包含 `main.py`，里面定义继承 `astrbot.api.star.Star` 的类。

```text
qq-agent-bridge/
  astrbot_plugins/
    astrbot_plugin_hello/
      main.py
      _conf_schema.json   # 可选
```

### 2.2 已支持的插件 API

- `from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult`
- `from astrbot.api.star import Context, Star`
- `from astrbot.api import logger, AstrBotConfig`
- `from astrbot.api import message_components as Comp`
- `@filter.command` / `@filter.command_group` / `@filter.event_message_type` /
  `@filter.platform_adapter_type` / `@filter.permission_type`
- `event.plain_result` / `event.image_result` / `event.chain_result` /
  `event.send` / `event.stop_event` / `event.unified_msg_origin`
- `Comp.Plain` / `Image` / `Video` / `Record` / `Face` / `At` / `File` / `Reply` / `Node`
- `Context.send_message(unified_msg_origin, chain)`
- `_conf_schema.json` 默认值 + `AstrBotConfig.save_config()`

### 2.3 分发顺序

AstrBot 插件先于 qq-agent-bridge 原生流程执行；插件 handler 里调用 `event.stop_event()` 可以阻止本次消息继续走原生/任务流程。

### 2.4 不支持

深度依赖 `astrbot.core` 内部实现、WebUI、平台 adapter 客户端、LLM 工具注册/钩子链的插件无法直接运行（例如 qq_tools 的视频分析工具）。这些需要单独移植或等兼容层扩展。

## 3. 视频回复标记

核心模型可以在回复里单独一行使用 `[VIDEO:本地绝对路径|显示名称]`，桥接会调用 OneBot `send_private_msg` 的 `video` 段把视频发给 QQ。
