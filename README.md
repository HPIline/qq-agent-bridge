# QQ AI 助手

把你自己的 QQ 变成一个有记忆、能动手的 AI 助手。

你给它发消息，它用你配置的任意大模型回答；你发图片它看得懂，发文件它能读，发视频它会看完再讲给你听；
你说"帮我做个表格并发我"，它会在自己的目录里做好，然后把文件直接发回你的 QQ。

它只处理**你自己的私聊**，没有群聊，没有陌生人。整套东西跑在你自己电脑上，模型用你自己的 key。

---

## 目录

- [它能做什么](#它能做什么)
- [上手三步](#上手三步)
- [配置：通常只要改 5 行](#配置通常只要改-5-行)
- [用起来](#用起来)
- [让它更像"你的"助手](#让它更像你的助手)
- [可选能力](#可选能力)
- [让它一直在线](#让它一直在线)
- [常见问题](#常见问题)
- [安全建议](#安全建议)
- [给开发者的说明](#给开发者的说明)
- [English](#english)
- [License](#license)

---

## 它能做什么

| 你说 / 你发 | 它做什么 |
| --- | --- |
| 随便聊聊 | 正常聊天，记得住之前聊过什么（长期记忆可关） |
| 发一张图 | 直接看图回答；认不出、拿不准的内容还会自己联网查一下再答 |
| 发一个视频 / B 站链接 | 下载 → 看画面 → 读字幕 → 听声音 → 给你一段"看完了，讲了什么"的总结 |
| 发 PDF / Word / Excel | 下载下来读内容，再回答你 |
| "帮我写个脚本，做好发我" | 在它的工作目录里把文件做出来，用 `[FILE:]` 标记发回 QQ |
| "提醒我明天 9 点开会" | 到点私聊提醒你 |
| "记一下待办：周五交报告" | 存进本地待办，`/待办` 随时看 |
| "帮我查个东西" | 可以联网搜索（可关），也可以让它先读你自己的本地知识库 |
| 长时间没找它 / 到点 | 它可以主动开口（默认**关闭**，想开就开） |

它干活的地方叫 **工作目录**（`workdir`），文件读写和命令执行都被限制在里面。
**建议单独建一个空目录给它玩**，比如 `~/qq-bot-workspace`。

## 上手三步

### 1. 让 QQ 能被程序接管（NapCat）

推荐用一个**小号**，不要用主号。

1. 下载安装 [NapCatQQ](https://github.com/NapNeko/NapCatQQ)（Windows 安装包 / macOS DMG / Linux 脚本）。
2. 打开 NapCat，用小号扫码登录。
3. 打开 NapCat 的 WebUI → 「网络配置」→ 新建 **WebSocket 服务器**：
   - 监听地址 `127.0.0.1`，端口 `3001`，消息格式 `array`
   - 保存后重启 NapCat 生效

### 2. 准备一个模型

任何 **OpenAI 兼容**接口都可以，比如：

| 你用哪家 | `api_base_url` | `model` |
| --- | --- | --- |
| OpenAI 官方 | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 各类中转 / 自建网关 | 服务商给的地址 | 服务商给的模型名 |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5:14b` 之类 |

想要"看图/看视频"这两项，模型本身得支持图片输入（多模态）。

### 3. 装好、填配置、启动

需要 Python 3.10+（推荐 3.12/3.13）。

```bash
git clone https://github.com/HPIline/qq-agent-bridge.git
cd qq-agent-bridge
cp config.example.json config.json     # Windows: copy config.example.json config.json
# 打开 config.json 填下面 5 行里的后 4 行
./start.sh                             # Windows: start.bat
```

首次运行会自动建 `.venv` 并装依赖。启动后给自己的小号发一句「你好」，收到回复就成功了。

日志在 `data/bridge.log`。

## 配置：通常只要改 5 行

```json
{
  "onebot_ws_url": "ws://127.0.0.1:3001",
  "full_access_qq": ["你的QQ号"],
  "api_base_url": "https://api.openai.com/v1",
  "api_key": "sk-你的密钥",
  "model": "gpt-4o-mini"
}
```

- `full_access_qq`：**必填**，允许使用机器人的 QQ 号（可以写多个）。不在列表里的私聊一律忽略。
- 其余键都有合理默认值，**不用动**。

不想把密钥写进文件？用环境变量，优先级比 `config.json` 高：

```bash
export QQBOT_API_KEY=sk-xxx
export QQBOT_FULL_ACCESS_QQ='["123456789"]'
```

其它常用的几项（都在 `config.json` 里，改完重启生效）：

| 想做什么 | 改哪个 |
| --- | --- |
| 换模型 / 换服务商 | `api_base_url`、`model` |
| 给它一个专用工作目录 | `workdir` |
| 状态文件别放项目里 | `data_dir` |
| 关掉联网搜索 / 命令执行 | `web_search_enabled`、`shell_enabled` |
| 关掉长期记忆 | `memory_enabled` |
| 让它主动找你 | `proactive_enabled` 及同组配置 |
| 让它按你的人设说话 | `persona_name`、`persona_prompt` |
| 开 Web 界面 | `web_enabled`、`web_token` |

**完整清单（180 项，含默认值和说明）：[CONFIG.md](CONFIG.md)**

## 用起来

### 命令

私聊里直接发，Web 界面里也一样：

| 命令 | 作用 |
| --- | --- |
| `/help` | 看所有命令 |
| `/new` | 忘掉当前话题，重新开始 |
| `/id` | 看当前会话编号 |
| `/提醒 喝水 明天9点` · `/提醒列表` · `/取消提醒 <id>` | 定时提醒 |
| `/待办 添加 周五交报告` · `/待办` · `/完成 <id>` | 待办清单 |
| `/日历` | 看今天有什么 |
| `/任务 <要做的事>` · `/任务列表` · `/任务取消 <id>` | 丢一个后台任务给它 |
| `/知识库 重建` · `/知识库 搜 关键词` | 把本地文档变成它能查的知识库 |
| `/天气 北京` · `/技能` | 内置小技能 |
| `/晨报` · `/晨报设置 08:30` | 每天早上给你发一份 |
| `/课表` · `/课表查看` · `/课表清除` | 发一张课表图片就能存下来 |
| `/话题` · `/静默` · `/唤醒` | 让它现在主动说一句 / 别打扰你 |

### 让它给你发文件

在它干活时告诉它"做好发我"，它会在回复里输出 `[FILE:绝对路径|文件名]`，桥接会自动把文件发到你的 QQ。
同理还有 `[IMAGE:...]`、`[VIDEO:...]`、`[FACE:14]`（QQ 表情）。

### 让它主动找你

默认是关的。想开：`"proactive_enabled": true`，然后按需要调：

- `proactive_fixed_times`：每天固定几点开口
- `proactive_idle_minutes`：多久没消息才主动开口
- `proactive_max_per_day` / `proactive_cooldown_minutes`：一天最多几次、两次之间隔多久
- `proactive_windows`：只在某个时间段打扰你
- `proactive_notes_file`：写在这个文件里的日程/待办，它开口时会顺带提

## 让它更像"你的"助手

不填的话，它就是一个普通中文助手。想让它有自己的性格：

```json
{
  "persona_name": "小助手",
  "persona_prompt": "说话简短，先给结论；拿不准就直说不确定，不要编。",
  "persona_ack_lines": ["收到，我看下。", "稍等，马上处理。"],
  "emoticon_examples": ["(・_・)", "(￣▽￣)"]
}
```

想要更完整的人设（长设定、附带资源文件），把它写成一个技能目录，放在 `persona_skill_home` 下：

```text
~/.agents/skills/my-persona/SKILL.md
```

```json
{ "persona_skill": "my-persona" }
```

提示词里会提示模型先读这份 `SKILL.md`，你可以把口癖、说话方式、背景设定都写进去。

私聊里发 `/角色` 可以随时切回人设模式；`/new` 会开一段新对话（旧对话会自动整理成长期记忆）。

## 可选能力

装哪个用哪个，不装不影响基础聊天。

### 看 PDF 里的字（OCR）

PDF 有文字层时不需要额外安装；扫描件需要本机有 poppler 和 tesseract：

```bash
brew install poppler tesseract          # macOS
sudo apt install poppler-utils tesseract-ocr   # Linux
```

Windows 装完把目录告诉程序即可：`export QQBOT_PDF_TOOL_DIR="C:\Program Files\poppler\Library\bin"`。

### 视频转写（语音转文字）

默认 `video_asr_backend: "auto"`，会按平台自动挑可用的后端：

```bash
pip install openai-whisper        # 通用（CPU 也能跑，慢）
pip install faster-whisper        # 更快，推荐
pip install -r requirements-macos.txt   # Apple Silicon 上最省事（mlx-whisper）
```

装不上也没关系——它会跳过转写，字幕和画面照样看。

### 语音回复（语音条）

默认关闭。想让它发语音，需要一个本地 GPT-SoVITS 服务：

```bash
pip install -r requirements-voice.txt   # 还需要 C 编译工具链
```

然后配 `tts_backend: "local"`、`tts_local_url`、`tts_models_dir`、`tts_character`、`tts_ref`。

### Web 工作台

不想开 QQ 也能聊、也能看提醒/待办/任务和日志：

```bash
pip install -r requirements-web.txt
```

```json
{ "web_enabled": true, "web_token": "换成一串足够长的随机字符" }
```

打开 `http://127.0.0.1:8080`，填 `web_token` 即可。

### 和别的程序互通

想让另一个程序（定时脚本、别的助手）借这个 QQ 号发消息、或者把 QQ 消息转给它处理，
用文件通道：往 `channels/to_qq/` 写一个 JSON 就发出去，QQ 收到的消息会落到 `channels/from_qq/`。
协议见 [channels/README.md](channels/README.md)。

### AstrBot 插件

生态里只依赖 `astrbot.api` 的简单插件可以直接跑（默认关闭）：

```json
{ "plugins_enabled": true }
```

把插件目录放进 `astrbot_plugins/`（每个插件一个子目录，里面有 `main.py`）。细节见 [VIDEO_ASTRBOT.md](VIDEO_ASTRBOT.md)。

## 让它一直在线

程序自己不管开机自启，用系统自带的服务管理器最省事。

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

**macOS（launchd）**：用 `launchctl` 注册一个 plist，把 `ProgramArguments` 指向 `.venv/bin/python bridge.py`。

**Windows**：用「任务计划程序」建一个"登录时启动"的任务，程序填 `.venv\Scripts\python.exe`，参数填 `bridge.py`。

配好之后把 `restart_command` 填上，`/restart` 命令就能用了：

```json
{ "restart_command": "systemctl restart qq-agent-bridge" }
```

## 常见问题

**发了消息没反应？**
先确认三点：NapCat 登录的是小号且在运行；发消息的 QQ 号在 `full_access_qq` 里；你发的是私聊不是群聊。
再看 `data/bridge.log`。

**启动就报"未配置模型 API key"？**
填 `config.json` 的 `api_key`，或者设环境变量 `QQBOT_API_KEY`。

**回复很慢 / 老是超时？**
`chat_effort` 调到 `low`，`chat_timeout` 调大。任务类可以保留 `task_effort: "max"`。

**它说"看不清这张图"？**
说明你配的模型不支持读图。换一个多模态模型（`model` 改成支持图片的），或者把 `vision_model` 单独指向一个多模态模型。

**视频没分析？**
`video_analysis_enabled` 是否为 `true`；长视频会慢，可以调小 `video_max_frames`。

**它把文件发不回来？**
`[FILE:]` 里必须是**运行程序这台机器**上的绝对路径，并且文件真实存在。

**会不会把电脑搞乱？**
文件读写和命令执行都被限制在 `workdir` 内。仍建议把 `workdir` 设成一个专门的空目录，别指向 `~` 或系统目录。

**能加群吗？**
目前只做私聊。

## 安全建议

- **密钥别进 Git**：`config.json` 已在 `.gitignore` 里；更推荐用 `QQBOT_API_KEY` 环境变量。
- **`full_access_qq` 只放自己**：列表里的人都能让它执行命令、读写文件。
- **`workdir` 用空目录**：别指到家目录、桌面或代码仓库。
- **Web 只监听本机**：`web_host` 保持 `127.0.0.1`；要远程就 SSH 隧道，不要直接暴露公网。
- **`web_token` 用随机长串**，别用 `123456`。
- QQ 账号风控、NapCat 使用风险由使用者自行承担。

## 给开发者的说明

- Python 3.10+，纯异步；核心模块见 `bridge.py`（编排）、`handlers.py`（消息处理管线）、
  `agent_client.py`（模型/工具/记忆）、`media.py`（媒体收发）、`message_utils.py`（提示词与消息分类）。
- 加一个配置项：在 `config.py` 的 `DEFAULTS` 里加键 → `python tools/gen_config_doc.py` 重新生成
  [CONFIG.md](CONFIG.md) → 在 `tools/gen_config_doc.py` 的 `DESCRIPTIONS` 里补一句说明
  （缺说明脚本会拒绝生成，测试也会拦住）。
- 跑测试与静态检查：

  ```bash
  python -m pip install -r requirements-dev.txt
  python -m pytest        # 300+ 用例
  ruff check .
  ```

- 加一个技能：在 `skills/` 下写个纯函数 → 在 `skills_registry.py` 里包成工具 →
  加进 `skills_enabled`。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 版本变化见 [CHANGELOG.md](CHANGELOG.md)。

## English

**Turn your own QQ account into an AI assistant.**

Send it a message and it answers with your own model (any OpenAI-compatible endpoint); send it a photo and it looks;
send a PDF or a video and it reads/watches it, then replies. It can also run tasks in its own workspace and send
the resulting files straight back to your QQ chat.

- **Private chat only**, no groups. Everything runs on your machine with your own API key.
- **Works on** Windows / macOS / Linux (`start.bat` / `start.sh`).
- **Configure** by editing `config.json` (see [`CONFIG.md`](CONFIG.md) for all ~180 options),
  or override anything with `QQBOT_<KEY>` environment variables.
- **Make it yours**: set `persona_name` / `persona_prompt`, or point `persona_skill` at a skill folder
  to load a full character.
- **Optional extras**: local OCR, video transcription, voice replies, a small web UI, and a file-based
  bridge so other programs can send/receive through your QQ account.

```bash
git clone https://github.com/HPIline/qq-agent-bridge.git && cd qq-agent-bridge
cp config.example.json config.json   # fill full_access_qq + api_key + model
./start.sh                           # start.bat on Windows
```

Documentation is in Chinese; code comments are mixed Chinese/English. Issues and PRs are welcome.

## License

[MIT](LICENSE)
