# 贡献指南

欢迎 issue 和 PR。

## 两条硬性要求

1. **不要提交个人数据**：真实 QQ 号、昵称、API key、token、个人绝对路径、私人聊天记录、
   个人项目名，都不要出现在代码、测试、文档或示例配置里。
2. **不要破坏跨平台**：新代码要能在 Windows / macOS / Linux 上跑；平台专有调用必须能降级
   （缺依赖时安静跳过，不要直接崩）。缺依赖就报错的写法请加上明确提示和安装指引。

## 开发流程

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt     # Windows: .venv\Scripts\python.exe
python -m pytest
ruff check .
```

提交前确认：

- [ ] `python -m pytest` 全绿
- [ ] `ruff check .` 无告警
- [ ] 新增配置项已同步到 `CONFIG.md`（见下）
- [ ] 没有把 `config.json`、`data/`、日志等运行期文件加进提交

## 加一个配置项

1. 在 `config.py` 的 `DEFAULTS` 里加键和默认值。
   - 路径类键要加进对应的元组：`_DATA_PATH_KEYS`（跟着 `data_dir` 走）、
     `_PROJECT_PATH_KEYS`（固定在项目里）、`_EXTERNAL_PATH_KEYS`（外部资源）。
2. 在 `tools/gen_config_doc.py` 的 `GROUPS` 里归组、`DESCRIPTIONS` 里写一句说明，
   然后重新生成手册：

   ```bash
   python tools/gen_config_doc.py
   ```

   脚本会因为缺少说明而拒绝生成，`tests/test_example_config.py` 也会拦住漏写。

3. 如果需要向后兼容旧键名，在 `config.py` 的 `LEGACY_KEYS` 里加一条映射
   （文件和 `QQBOT_*` 环境变量都会自动兼容，启动时日志会提示改名）。
4. 只在 `config.example.json` 里放**必填/最常用**的键，其余交给默认值和 `CONFIG.md`。

## 加一个技能

1. 在 `skills/` 下新建模块，写一个纯函数，例如 `def skill_foo(query: str) -> str:`。
2. 在 `skills_registry.py` 的 `load_skills()` 里用 `_wrap(...)` 包成工具。
3. 在 `DEFAULTS["skills_enabled"]` 的说明和 `skills/__init__.py` docstring 里提一句。
4. 补测试（参考 `tests/test_skills_registry.py`）。

## 提交信息

一句话说清"做了什么"，中文英文都行：

```text
fix: Windows 下 file:// 视频路径解析错误
feat: 支持在配置里覆盖主动话题提示词
docs: 补充 systemd 常驻示例
```
