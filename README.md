# QQ AI 助手

基于 [NapCat](https://github.com/NapNeko/NapCatQQ)（OneBot v11）的 QQ 私聊 AI 助手，可对接任意 OpenAI 兼容模型。

支持文字对话、图片理解、视频分析、文件收发与任务执行：收到消息后交给模型处理，模型可以在受限的工作目录内
读写文件、执行命令、联网检索，并把产出的文件直接发回 QQ。全部数据与密钥保存在本机。

---

## 目录

- [功能](#功能)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置](#配置)
- [使用](#使用)
- [自定义人格](#自定义人格)
- [可选能力](#可选能力)
- [常驻运行](#常驻运行)
- [常见问题](#常见问题)
- [安全建议](#安全建议)
- [开发](#开发)
- [English](#english)
- [License](#license)

---

## 功能

| 能力 | 说明 |
| --- | --- |
| 文字对话 | 多轮上下文；长期记忆持久化到本地 SQLite，可关闭 |
| 图片理解 | 图片直接交给多模态模型；描述中出现不确定项时自动联网补查 |
| 视频分析 | 下载后抽帧逐帧描述，结合字幕与语音转写，输出结构化总结 |
| 文件收发 | 读取 QQ 发来的文档（PDF 支持 OCR 兜底）；模型产出的文件以 `[FILE:]` 标记发回 |
| 任务执行 | 自动区分闲聊与任务；任务先回执再执行，长任务分阶段汇报并等待"继续/停止" |
| 日程事务 | 提醒、待办、日历、后台任务队列，数据存于本地 SQLite |
| 知识库 | 索引本地 `.md` / `.txt` / `.pdf`，支持命令检索与模型主动检索 |
| 主动消息 | 定时、空闲或日程前主动开口；默认关闭，可配置时段、频率与冷却 |
| 人格设定 | 默认通用中文助手；可通过配置项或技能目录定义人设、语气与媒体使用频率 |
| 外部程序互通 | 基于文件的双向通道，其他程序可借该 QQ 号发消息，QQ 消息也可转交处理 |
| Web 工作台 | 浏览器内聊天、查看提醒/待办/任务/日志（可选） |
| 第三方插件 | 兼容 AstrBot 生态中仅依赖 `astrbot.api` 的简单插件（可选） |

模型能力的读写边界由配置项 `workdir` 限定，文件与命令工具均无法越出该目录。

## 环境要求

- Python 3.10+（推荐 3.12 / 3.13）
- [NapCatQQ](https://github.com/NapNeko/NapCatQQ)（提供 OneBot v11 WebSocket 服务）
- 一个 OpenAI 兼容模型的 API Key（官方、DeepSeek、中转站、自建网关、本地 Ollama 均可）

图片与视频分析需要所选模型支持图片输入。

## 快速开始

### 1. 配置 NapCat

建议使用 QQ 小号，避免影响主号。

1. 安装 NapCatQQ（Windows 安装包 / macOS DMG / Linux 脚本）。
2. 打开 NapCat，用小号扫码登录。
3. 进入 NapCat WebUI →「网络配置」→ 新建 **WebSocket 服务器**：
   - 监听地址 `127.0.0.1`，端口 `3001`，消息格式 `array`
   - 保存后重启 NapCat 生效

### 2. 安装

```bash
git clone https://github.com/HPIline/qq-agent-bridge.git
cd qq-agent-bridge
./start.sh          # macOS / Linux；首次运行会创建 .venv 并安装依赖
start.bat           # Windows
```

手动安装等价于：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-agno.txt
# Windows: .venv\Scripts\python.exe
```

### 3. 配置

```bash
cp config.example.json config.json      # Windows: copy config.example.json config.json
```

编辑 `config.json`，至少填写以下字段：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| `onebot_ws_url` | NapCat 的 WebSocket 地址 | `ws://127.0.0.1:3001` |
| `full_access_qq` | **必填**，允许使用机器人的 QQ 号，可填多个 | `["123456789"]` |
| `api_base_url` | OpenAI 兼容接口地址 | `https://api.openai.com/v1` |
| `api_key` | 接口密钥 | `sk-...` |
| `model` | 模型名 | `gpt-4o-mini` |

常用服务商配置示例：

| 服务商 | `api_base_url` | `model` |
| --- | --- | --- |
| OpenAI 官方 | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5:14b` |
| 中转 / 自建网关 | 服务商提供的地址 | 服务商提供的模型名 |

### 4. 启动

```bash
./start.sh          # macOS / Linux
start.bat           # Windows
```

启动后向小号发送「你好」验证连通性。日志位于 `data/bridge.log`。

## 配置

配置优先级：**环境变量 > `config.json` > 内置默认值**。

- 配置文件查找顺序：`$QQBOT_CONFIG` → 项目目录 `config.json` → 系统配置目录
  （Windows `%APPDATA%\qq-agent-bridge`，macOS `~/Library/Application Support/qq-agent-bridge`，
  Linux `$XDG_CONFIG_HOME/qq-agent-bridge`）。
- 任意配置项均可用环境变量覆盖，格式为 `QQBOT_<键名大写>`，值按 JSON 解析：

  ```bash
  export QQBOT_API_KEY=sk-xxx
  export QQBOT_FULL_ACCESS_QQ='["123456789"]'
  export QQBOT_WORKDIR=/var/lib/qq-bot/workspace
  ```

- 状态数据（日志、SQLite、会话、记忆）默认存放于 `data/`，可用 `data_dir` 重定位；
  `channels/`、`outbox/` 等工作目录固定于项目内。

**完整配置手册（180 项，含默认值与说明）：[CONFIG.md](CONFIG.md)**

常见调整：

| 目的 | 配置项 |
| --- | --- |
| 更换模型或服务商 | `api_base_url`、`model` |
| 指定独立工作目录 | `workdir` |
| 重定位状态文件 | `data_dir` |
| 关闭联网搜索 / 命令执行 | `web_search_enabled`、`shell_enabled` |
| 关闭长期记忆 | `memory_enabled` |
| 开启主动消息 | `proactive_enabled` 及同组配置 |
| 自定义人格 | `persona_name`、`persona_prompt` |
| 开启 Web 工作台 | `web_enabled`、`web_token` |

## 使用

私聊发送消息即可，无需前缀。内置命令（Web 工作台同样可用）：

| 命令 | 说明 |
| --- | --- |
| `/help` | 列出全部命令 |
| `/new` | 重置当前会话 |
| `/id` | 查看当前会话 ID |
| `/提醒 喝水 明天9点` · `/提醒列表` · `/取消提醒 <id>` | 定时提醒 |
| `/待办 添加 周五交报告` · `/待办` · `/完成 <id>` · `/删除待办 <id>` | 待办清单 |
| `/日历` | 查看日历 |
| `/任务 <描述>` · `/任务列表` · `/任务取消 <id>` | 后台任务队列 |
| `/知识库 重建` · `/知识库 搜 <关键词>` | 本地知识库 |
| `/天气 北京` · `/技能` | 内置技能 |
| `/晨报` · `/晨报设置 08:30` | 每日晨报 |
| `/课表` · `/课表查看` · `/课表清除` | 课表导入与管理 |
| `/话题` · `/静默` · `/唤醒` | 主动消息控制 |
| `/角色` | 切换回人格模式 |

模型在回复中可输出媒体标记，由桥接转换为真实消息：

| 标记 | 说明 |
| --- | --- |
| `[FILE:/绝对路径\|文件名]` | 发送文件 |
| `[IMAGE:/绝对路径或URL]` | 发送图片 |
| `[VIDEO:/绝对路径\|显示名]` | 发送视频 |
| `[FACE:14]` | 发送 QQ 内置表情 |
| `[MFACE:emoji_id\|emoji_package_id\|key\|说明]` | 发送商城表情 |
| `[VOICE:文本]` | 发送语音（需配置 TTS） |

主动消息默认关闭。开启后可通过 `proactive_fixed_times`（固定时间点）、`proactive_idle_minutes`
（空闲多久触发）、`proactive_max_per_day` / `proactive_cooldown_minutes`（频率与冷却）、
`proactive_windows`（可打扰时段）调节；`proactive_notes_file` 中记录的日程会在开口时被引用。

## 自定义人格

默认配置为通用中文助手。两种自定义方式：

**配置项**（适合简短设定）：

```json
{
  "persona_name": "小助手",
  "persona_prompt": "说话简短，先给结论；不确定时明确说明，不编造内容。",
  "persona_ack_lines": ["收到，我看下。", "稍等，马上处理。"],
  "emoticon_examples": ["(・_・)", "(￣▽￣)"]
}
```

**技能目录**（适合长设定与附带资源）：在 `persona_skill_home`（默认 `~/.agents/skills`）下建立

```text
~/.agents/skills/my-persona/SKILL.md
```

并配置：

```json
{ "persona_skill": "my-persona" }
```

提示词会附带该 `SKILL.md` 的绝对路径，由模型自行读取。

相关配置：`persona_enabled`（开关）、`persona_reset_turns` / `persona_reset_hours`（会话轮换阈值）、
`chat_style_guide` / `media_frequency_guide` / `proactive_topic_guide`（直接覆盖内置提示词片段）、
`extra_skill_triggers`（命中关键词时提示模型先读指定技能）。

## 可选能力

以下能力按需启用，未安装依赖不影响基础对话。

### PDF OCR

PDF 含文字层时无需额外依赖；扫描件需本机安装 poppler 与 tesseract：

```bash
brew install poppler tesseract                 # macOS
sudo apt install poppler-utils tesseract-ocr   # Linux
```

Windows 安装后将目录写入环境变量：`QQBOT_PDF_TOOL_DIR="C:\Program Files\poppler\Library\bin"`。

### 视频语音转写

默认 `video_asr_backend: "auto"`，按平台选择可用后端：

```bash
pip install openai-whisper                # 通用，CPU 可用
pip install faster-whisper                # 更快，推荐
pip install -r requirements-macos.txt     # Apple Silicon（mlx-whisper）
```

缺少任一后端时自动跳过转写，画面与字幕分析仍正常执行。

### 语音回复

默认关闭。需要本地 GPT-SoVITS 服务：

```bash
pip install -r requirements-voice.txt     # 需 C 编译工具链
```

配置 `tts_backend: "local"`、`tts_local_url`、`tts_models_dir`、`tts_character`、`tts_ref`。

### Web 工作台

```bash
pip install -r requirements-web.txt
```

```json
{ "web_enabled": true, "web_token": "随机长字符串" }
```

访问 `http://127.0.0.1:8080`，填入 `web_token` 即可。

### 外部程序互通

其他程序（定时脚本、其他助手）可通过文件通道借该 QQ 号发送消息，QQ 收到的消息也可转交处理：
写入 `channels/to_qq/` 的 JSON 信封会被发送，QQ 消息记录在 `channels/from_qq/`。
协议详见 [channels/README.md](channels/README.md)。

### AstrBot 插件

兼容仅依赖 `astrbot.api` 的简单插件，默认关闭：

```json
{ "plugins_enabled": true }
```

插件放入 `astrbot_plugins/`（每个插件一个子目录，内含 `main.py`）。详见 [VIDEO_ASTRBOT.md](VIDEO_ASTRBOT.md)。

## 常驻运行

程序本身不负责开机自启，建议交由系统服务管理器。

**Linux（systemd）**

```ini
# /etc/systemd/system/qq-agent-bridge.service
[Unit]
Description=QQ AI 助手
After=network-online.target

[Service]
WorkingDirectory=/opt/qq-agent-bridge
ExecStart=/opt/qq-agent-bridge/.venv/bin/python bridge.py
Restart=always
User=youruser

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now qq-agent-bridge
```

**macOS（launchd）**：注册 plist，将 `ProgramArguments` 指向 `.venv/bin/python bridge.py`。

**Windows**：在「任务计划程序」中创建登录时启动的任务，程序填 `.venv\Scripts\python.exe`，参数填 `bridge.py`。

配置 `restart_command` 后，`/restart` 命令可用：

```json
{ "restart_command": "systemctl restart qq-agent-bridge" }
```

## 常见问题

**发送消息无响应**
依次检查：NapCat 是否运行且已用小号登录；发送方 QQ 号是否在 `full_access_qq` 中；是否为私聊消息。
仍无响应时查看 `data/bridge.log`。

**启动报"未配置模型 API key"**
填写 `config.json` 的 `api_key`，或设置环境变量 `QQBOT_API_KEY`。

**回复慢或频繁超时**
将 `chat_effort` 调为 `low`、`chat_timeout` 调大；任务类可保留 `task_effort: "max"`。

**提示"看不清这张图片"**
当前模型不支持图片输入。更换多模态模型，或将 `vision_model` 单独指向多模态模型。

**视频未被分析**
确认 `video_analysis_enabled` 为 `true`。长视频耗时较长，可调小 `video_max_frames`。

**模型无法发回文件**
`[FILE:]` 中的路径必须是运行程序所在机器上的绝对路径，且文件真实存在。

**担心影响本机文件**
文件与命令工具被限制在 `workdir` 内。建议将 `workdir` 设为专用空目录，不要指向家目录或系统目录。

**是否支持群聊**
当前仅支持私聊。

## 安全建议

- **密钥不要入库**：`config.json` 已在 `.gitignore` 中；更推荐通过 `QQBOT_API_KEY` 环境变量注入。
- **`full_access_qq` 仅填写可信账号**：列表内的账号可以使用命令执行与文件读写能力。
- **`workdir` 使用专用目录**：避免指向家目录、桌面或代码仓库。
- **Web 工作台仅监听本机**：保持 `web_host` 为 `127.0.0.1`；需要远程访问时使用 SSH 隧道或反向代理 + HTTPS。
- **`web_token` 使用随机长字符串**。
- QQ 账号风控与 NapCat 使用风险由使用者自行承担。

## 开发

- Python 3.10+，全异步实现。核心模块：`bridge.py`（编排）、`handlers.py`（消息处理管线）、
  `agent_client.py`（模型 / 工具 / 记忆）、`media.py`（媒体收发）、`message_utils.py`（提示词与消息分类）。
- 新增配置项：在 `config.py` 的 `DEFAULTS` 中添加键 → 运行 `python tools/gen_config_doc.py`
  重新生成 [CONFIG.md](CONFIG.md)（未补说明时脚本会拒绝生成，测试同样会拦截）。
- 新增技能：在 `skills/` 下实现纯函数 → 在 `skills_registry.py` 中注册 → 加入 `skills_enabled`。
  详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest        # 300+ 用例
ruff check .
```

版本变更见 [CHANGELOG.md](CHANGELOG.md)。

## English

An AI assistant for QQ private chats, built on [NapCat](https://github.com/NapNeko/NapCatQQ) (OneBot v11)
and any OpenAI-compatible model endpoint.

- Understands text, images, videos and documents; can run tasks inside a sandboxed working directory
  and send generated files back to the chat.
- Includes reminders, todos, a task queue, a local knowledge base and optional proactive messages.
- Runs on Windows / macOS / Linux (`start.bat` / `start.sh`).
- Configure via `config.json` or `QQBOT_<KEY>` environment variables; all ~180 options are documented
  in [`CONFIG.md`](CONFIG.md).
- Persona is configurable (`persona_name` / `persona_prompt`), or loadable from a skill directory.

```bash
git clone https://github.com/HPIline/qq-agent-bridge.git && cd qq-agent-bridge
cp config.example.json config.json   # fill in full_access_qq, api_key and model
./start.sh                           # start.bat on Windows
```

Documentation is written in Chinese. Issues and pull requests are welcome.

## License

[MIT](LICENSE)
