# 文件通道协议（channels/）

除了 QQ 私聊，本项目还提供一套**基于文件的双向通道**，方便另一个程序（主控 Agent、脚本、定时任务、
其它机器人）与本桥接互通。所有路径都可以在 `config.json` 里改。

```text
外部程序 ──写 JSON 信封──► channels/to_qq/          桥接每 5 秒扫描并以机器人身份发到 QQ
QQ 消息 ──追加 JSONL───► channels/from_qq/feedback.jsonl
QQ 消息（/本机 前缀）──► channels/from_qq/main.jsonl    不交给机器人，直接转给主控
主控状态 ──写 Markdown──► channels/state/agent-status.md  机器人可读取
等待回复 ──pending.json──► channels/state/pending.json     捕获用户下一条回复
```

## 1. 主控 → QQ：信封格式

在 `channels/to_qq/` 下写一个 `.json` 文件（UTF-8），格式：

```json
{
  "to": ["你的QQ号"],
  "text": "要发送的内容",
  "kind": "report",
  "id": "可选，唯一编号"
}
```

- 桥接扫描到文件后立即发送，然后把文件归档到 `channels/to_qq/sent/`。
- `text` 里可以使用媒体标记（见下表），会被解析成真实消息而不是纯文本。

| 标记 | 含义 |
| --- | --- |
| `[FILE:/绝对路径\|显示名]` | 发送文件 |
| `[IMAGE:/绝对路径或URL]` | 发送图片 |
| `[VIDEO:/绝对路径\|显示名]` | 发送视频 |
| `[FACE:14]` | 发送 QQ 内置表情 |
| `[MFACE:emoji_id\|emoji_package_id\|key\|说明]` | 发送商城表情 |
| `[VOICE:文本]` | 发送语音（需要配置 TTS；见 `tts_backend`） |

## 2. QQ → 主控

- 普通消息：追加到 `channels/from_qq/feedback.jsonl`，每行一个 JSON 对象，带行数/字节上限
  （`inbox_log_max_lines` / `inbox_log_max_bytes`）。
- `/本机` 前缀消息：写入 `channels/from_qq/main.jsonl`，桥接只回复“已转给主控”，不会调用模型。
  前缀列表用 `main_agent_prefixes` 配置。

## 3. 等待用户回复（决断 / 任务阶段）

主控写 `channels/state/pending.json`：

```json
{
  "kind": "decision",
  "status": "waiting",
  "id": "decision-1",
  "prompt": "需要用户确认的问题"
}
```

桥接会把用户的下一条回复写回该文件的 `reply` 字段并把 `status` 改成 `answered`。
任务分阶段等待用同一个文件，`kind` 为 `task_stage`。

## 4. 状态文件

`channels/state/agent-status.md` 由外部主控维护、机器人只读，内容会作为上下文注入，
适合放“当前正在做什么 / 下一步计划”。

## 5. 兼容旧目录

`outbox/`、`inbox/feedback.log`、`decisions/pending.json`、`agent-status.md` 是历史路径，
启动时会自动迁移到 `channels/` 下，迁移后可以安全删除。
