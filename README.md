<div align="center">

# iatcoder

**轻量、本地、有记忆的终端 coding agent**

iatcoder 跑在本地仓库里，接上一个模型 provider，就能读代码、跑命令、改文件、
保留运行证据，并把有价值的上下文沉淀成本地记忆。

---

## iatcoder 是什么

iatcoder 是一个本地终端里的 coding agent，运行在你的仓库上下文里。一次 agent 运行会被拆成几个可观察的部分：

- **provider profile**：决定调用哪个模型、哪个 endpoint、用什么协议。
- **context**：把系统提示、仓库信息、skills、记忆和最近对话装进 prompt。
- **tools**：文件读取、搜索、shell、写文件、patch、子 agent 都走统一工具协议。
- **approval / sandbox**：写操作和 shell 命令可以被审批或沙箱限制。
- **session / run evidence**：对话、事件流、trace、report 都写到本地 `.iatcoder/`。
- **memory / dream**：把 daily log 整理成长期 topic，下次 session 可以继续用。

iatcoder 关注本地 coding agent 的工程边界：配置清楚、任务能续接、结果能复盘。

---

## 快速开始

### 安装

```bash
pip install iatcoder
```

或者从源码安装：

```bash
git clone <repo-url>
cd iatcoder
pip install -e .
```

### 配置 API Key

推荐方式 — 环境变量：

```bash
# DeepSeek（默认 provider）
export DEEPSEEK_API_KEY=sk-xxxx

# 或者 OpenAI 兼容接口
export OPENAI_API_KEY=sk-xxxx
```

也支持 `.env` 文件（放在项目根目录）：

```env
DEEPSEEK_API_KEY=sk-xxxx
```

其他支持的 key 环境变量名：

| Provider  | API Key 环境变量        | Base URL 环境变量      |
|-----------|------------------------|------------------------|
| openai    | `OPENAI_API_KEY`       | `OPENAI_BASE_URL`      |
| anthropic | `ANTHROPIC_API_KEY`    | `ANTHROPIC_BASE_URL`   |
| deepseek  | `DEEPSEEK_API_KEY`     | `DEEPSEEK_BASE_URL`    |

### 启动

```bash
# 在项目仓库目录下直接运行
iatcoder

# 指定 provider
iatcoder --provider deepseek

# 指定模型和 base_url
iatcoder --provider openai --model gpt-4o --base-url https://api.openai.com/v1

# 一步式 prompt（不进入交互模式）
iatcoder "给这个项目的 README 加一个 badges 区域"

# 从上次的 session 恢复
iatcoder --resume latest
```

启动后会看到工作台欢迎界面：

```
+------------------------------------------------------------------------------+
|                                             ^\                               |
|                                  /        //o__o                             |
|                                 /\       /  __/                              |
|                                  \ \______\  /                               |
|                                    \         /                               |
|                                     \ \----\ \                               |
|                                    \_\_   \_\_\                              |
|                                   iatcoder                                   |
|                              local coding agent                              |
|                          calm shell, ready for work                          |
+------------------------------------------------------------------------------+
```

---

## 使用指南

### 交互模式

iatcoder 支持三种交互模式：

| 模式       | 触发条件                                | 说明                                                           |
|------------|----------------------------------------|----------------------------------------------------------------|
| **TUI**    | `iatcoder --tui` 或终端是 tty          | 基于 Textual 的终端 UI，功能最完整                             |
| **REPL**   | `iatcoder --repl` 或 stdin 不是 tty    | 行提示符模式，输入 `iatcoder>` 后开始对话                     |
| **One-shot** | 传入 prompt 参数                      | 执行单次请求后退出，适合脚本集成                               |

默认情况下在终端直接运行会进入 TUI 模式。

### REPL 用法

```bash
$ iatcoder --repl

+------------------------------------------------------------------------------+
|                                             ^\                               |
|                                  /        //o__o                             |
|                                 /\       /  __/                              |
|                                  \ \______\  /                               |
|                                    \         /                               |
|                                     \ \----\ \                               |
|                                    \_\_   \_\_\                              |
|                                   iatcoder                                   |
|                              local coding agent                              |
|                          calm shell, ready for work                          |
+------------------------------------------------------------------------------+
| WORKSPACE  /home/user/my-project                                              |
| MODEL      deepseek-v4-pro    BRANCH          main                           |
| APPROVAL   ask                SESSION         7a3f2b...                      |
+------------------------------------------------------------------------------+

iatcoder> 帮我把 src/utils.py 里的 parse_config 函数加上类型注解

# ... agent 开始工作，读代码、改文件 ...

iatcoder> /exit   # 退出
```

### 命令行参数

| 参数                   | 默认值            | 说明                                                         |
|------------------------|-------------------|--------------------------------------------------------------|
| `prompt`               | —                 | 可选的 one-shot prompt                                       |
| `--provider`           | `openai`          | Provider profile：`openai` / `anthropic` / `deepseek`        |
| `--model`              | provider 默认     | 模型名覆盖                                                   |
| `--base-url`           | provider 默认     | API base URL 覆盖                                            |
| `--api-key`            | 环境变量          | API key 覆盖                                                 |
| `--cwd`                | `.`               | 工作目录                                                     |
| `--config`             | —                 | TOML 配置文件路径                                            |
| `--resume`             | —                 | 恢复指定 session（传 `latest` 恢复最近一个）                 |
| `--approval`           | `ask`             | 审批策略：`ask` / `auto` / `never`                           |
| `--sandbox`            | `off`             | 沙箱模式：`off` / `best_effort` / `required`                 |
| `--max-steps`          | `50`              | 每次请求最大工具/模型迭代次数                                |
| `--max-new-tokens`     | provider 感知     | 每次 step 最大输出 token（anthropic: 32000, openai: 8192）   |
| `--temperature`        | `0.2`             | 采样温度                                                     |
| `--tui`                | —                 | 启动 Textual 终端 UI                                         |
| `--repl`               | —                 | 使用行式 REPL                                                |
| `--memory-dir`         | —                 | 记忆目录，默认 `.iatcoder/memory`                            |
| `--no-auto-dream`      | —                 | 禁用自动记忆整理                                             |
| `--dream-interval`     | `24.0`            | 自动 dream 间隔（小时）                                      |
| `--dream-min-sessions` | `5`               | 触发 dream 的最少新 session 数                               |
| `--openai-timeout`     | `300`             | Provider 请求超时（秒）                                      |
| `--secret-env-name`    | —                 | 追加敏感环境变量名（trace/report 中脱敏）                    |

### TOML 配置文件

全局配置：`~/.config/iatcoder/config.toml`

项目配置：在项目根目录放 `.iatcoder.toml`

```toml
provider = "deepseek"

[providers.deepseek]
model = "deepseek-v4-pro"
base_url = "https://api.deepseek.com/v1"

[providers.openai]
model = "gpt-4o"
base_url = "https://api.openai.com/v1"

[sandbox]
mode = "best_effort"
```

### 环境变量

顶层配置（优先于配置文件）：

| 变量                  | 说明              |
|-----------------------|-------------------|
| `IATCODER_PROVIDER`   | 指定 provider     |
| `IATCODER_API_KEY`    | API key           |
| `IATCODER_BASE_URL`   | Base URL          |
| `IATCODER_MODEL`      | 模型名            |

---

## Slash 命令

在 REPL 或 TUI 中输入以下命令：

| 命令                           | 说明                        |
|--------------------------------|-----------------------------|
| `/help`                        | 显示帮助信息                |
| `/exit` 或 `/quit`             | 退出                        |
| `/memory`                      | 查看长期记忆                |
| `/working-memory`              | 查看工作记忆                |
| `/remember <text>`             | 记录一条笔记到 daily log    |
| `/dream`                       | 手动触发记忆整理            |
| `/skills`                      | 列出可用的 skills           |
| `/plan <topic> [path]`         | 进入计划模式                |
| `/plan-exit`                   | 退出计划模式                |
| `/mode`                        | 查看当前运行时模式          |
| `/session`                     | 查看当前 session 信息       |
| `/usage`                       | 查看模型用量和上下文统计    |
| `/model [name]`                | 查看或切换模型              |
| `/history`                     | 列出所有历史 session        |
| `/resume <id 或 index 或 latest>` | 恢复指定 session         |
| `/clear`                       | 开启新 session              |
| `/compact`                     | 手动压缩对话历史            |
| `/reset`                       | 重置当前 session            |
| `/context`                     | 查看上下文使用详情          |
| `/agents`                      | 查看子 agent 状态           |
| `/subagent <args>`             | 运行子 agent                |

---

## Session 管理

每次对话都是一个 **session**，保存在 `.iatcoder/sessions/` 目录下。

关键操作：

1. **查看历史 session**：在 REPL 中输入 `/history`
2. **恢复 session**：`/resume latest`（最近一个）或 `/resume <session-id>`
3. **从命令行恢复**：`iatcoder --resume latest`
4. **开启新 session**：`/clear`

Session 目录结构：

```
.iatcoder/
├── sessions/          # 会话记录
│   ├── <session-id>/
│   │   ├── events/    # 事件流
│   │   └── runs/      # 每次 ask 的运行记录
│   │       └── <run-id>/
│   │           ├── trace.jsonl
│   │           └── report.md
├── memory/            # 长期记忆
└── sandbox/           # 沙箱工件
```

---

## Memory / Dream 系统

iatcoder 会自动把 session 中的关键信息整理成**长期记忆**（称作 "dream"），下次启动时可以继续使用。

- **手动记录**：在对话中用 `/remember 记得...` 添加笔记
- **查看记忆**：`/memory`
- **触发整理**：`/dream`
- **自动整理**：每 24 小时或每 5 个新 session 后自动触发
- **禁用**：`iatcoder --no-auto-dream`

---

## Provider 支持

| Provider   | 协议       | 默认模型            | 默认端点                                   |
|------------|------------|---------------------|--------------------------------------------|
| openai     | OpenAI 兼容 | gpt-5.4             | `https://www.right.codes/codex/v1`         |
| anthropic  | Anthropic  | claude-sonnet-4-6   | `https://www.right.codes/claude/v1`        |
| deepseek   | OpenAI 兼容 | deepseek-v4-pro     | `https://api.deepseek.com/v1`              |

> 注意：openai 和 anthropic 的默认端点指向第三方代理 `right.codes`。如果需要直连官方 API，通过 `--base-url` 或配置文件覆盖。deepseek 默认直连官方 API。

示例 — 直连 OpenAI：

```bash
export OPENAI_API_KEY=sk-xxx
iatcoder --provider openai --model gpt-4o --base-url https://api.openai.com/v1
```

示例 — 直连 DeepSeek：

```bash
export DEEPSEEK_API_KEY=sk-xxx
iatcoder --provider deepseek --model deepseek-chat
```
