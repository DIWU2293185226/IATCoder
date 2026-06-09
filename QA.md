# iatcoder 架构范式与对比

## Q1: iatcoder 用的是什么样的 Agent 设计范式？ReAct、Plan-and-Execute 还是其他的？

**iatcoder 的核心是 ReAct（Reasoning + Acting）范式，在此之上叠加了可选的 Plan 模式和分层记忆系统。**

### 核心循环：ReAct

`Engine.run_turn()`（[engine.py](iatcoder/core/engine.py#L71)）实现了经典的 ReAct 循环：

```
用户请求 → 组装 prompt → 调用 LLM → 解析输出
                                           │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
               <tool> 调用               <final> 回答           格式错误 (retry)
                    │                        │                        │
              执行工具 ← 记录结果     返回最终答案              注入重试提示 ─→ 继续循环
                    │
                    └── 继续循环 ──────────→
```

每一轮迭代都是：**Reason（模型推理）→ Act（工具执行）→ Observe（结果注入下一轮 prompt）**，直到模型输出 `<final>` 为止。这是最标准的 ReAct 模式。

### 可选的 Plan 模式

`PlanModeManager`（[plan_mode.py](iatcoder/core/plan_mode.py#L15)）提供了一种写受限的"先规划再行动"阶段：

- 通过 `/plan <topic>` 进入 plan 模式后，模型只能**读取**文件和写入指定的 plan 工件（`.iatcoder/plans/xxx-plan.md`）
- plan 文件写完后，模型才能返回 `<final>` 回答自动退出 plan 模式
- Plan 模式下的工具集由 `tool_profiles.py` 约束，`write_file`/`patch_file` 只能写 plan 文件

但 iatcoder **不是**纯粹的 Plan-and-Execute 架构（如 Adept ACT-1 或 Voyager），因为：

- Plan 模式是**可选进入**的，不是每次任务的必需阶段
- 规划和执行使用**同一个模型**，没有分离的 planner 和 executor
- plan 文件并不绑定后续执行——退出 plan 模式后模型可以自由行动

### 本质定位

iatcoder = **ReAct + 可选的 Plan 约束 + 分层记忆增强 + 子 agent 委派**

| 范式特征 | iatcoder |
|----------|----------|
| 循环驱动 | ReAct（model → tool → model → ...） |
| 协议 | 纯文本 `<tool>/<final>` XML 标签（非 function calling） |
| 规划 | 可选，`/plan` 进入写受限阶段，非强制 |
| 记忆 | 双层：working memory + durable memory（dream 整合） |
| 子 agent | WorkerManager 支持后台 Explore/Worker 线程 |
| 技能 | SKILL.md 预定义工作流，通过 `/skill` 调用 |
| 状态检查点 | checkpoints + resume 续接能力 |
| 安全 | approval policy + sandbox + 路径逃逸检测 |

### 关键设计决策：纯文本协议

iatcoder 不使用 LLM 的 structured output / function calling 功能，而是自己用正则解析 `<tool>{"name":"xxx","args":{...}}</tool>` 或 `<tool name="xxx" path="..."><content>...</content></tool>` 格式。这带来了：

- **优点**：provider 无关，任何能生成文本的 LLM 都能用（OpenAI / Anthropic / DeepSeek / 本地模型）
- **缺点**：解析比 function calling 脆弱，模型偶尔会格式错误触发 retry

---

## Q2: iatcoder 和 Claude Code 的区别是什么？

| 维度 | iatcoder | Claude Code |
|------|----------|-------------|
| **设计范式** | ReAct + 可选 Plan + 子 agent | Tool-Use Agent（function calling） |
| **协议** | 纯文本 `<tool>/<final>` 标签，正则解析 | LLM structured output / function calling |
| **模型支持** | provider 无关（OpenAI / Anthropic / DeepSeek / 自建） | 仅 Anthropic Claude |
| **记忆系统** | 双层：working memory（会话级）+ durable memory（dream 整合到 topics/） | 基于对话上下文 + 项目记忆文件（CLAUDE.md） |
| **记忆整合** | `/dream` 命令将 daily log 提炼为分类 topic 文件 | 无显式整合机制 |
| **Plan 模式** | 内置 `/plan`，写受限的规划阶段 | /init 项目初始化，无严格 plan 模式 |
| **子 agent** | WorkerManager 支持后台 Explore/Worker 线程并行工作 | /spawn 启动子对话，有 Explore 和 Think 模式 |
| **技能系统** | SKILL.md 前端元数据定义可被发现的工作流 | CLAUDE.md 内嵌 hook 和指令 |
| **工具注册** | `tools/registry.py` 统一注册，按 profile 分类 | 内置工具集 + MCP 扩展服务器 |
| **安全** | approval policy（auto/ask/never）+ sandbox（bubblewrap）+ 路径逃逸检测 | permission levels（allow/deny/ask-by-default）+ 文件系统守卫 |
| **上下文管理** | ContextManager 按 section 预算控制，超预算自动压缩 | 基于 API 的 prompt caching |
| **运行证据** | per-run trace.jsonl + report.json + task_state.json | ~/.claude/logs + /summary |
| **续接** | `/resume` + checkpoint 系统 | 自动续接 + /compact |
| **TUI** | Textual 框架，Crystal 终端 UI | 内置 Terminal UI（Crystal 终端） |
| **审查模式** | 无 | /review 专门代码审查模式 |
| **开源** | 是 | 否 |
| **依赖** | 轻量，~10 个核心依赖 | 完整的 Node.js 包 |

### 架构差异详解

#### 1. 协议层不同

iatcoder 用纯文本标签：

```
<tool>{"name":"read_file","args":{"path":"main.py","start":1,"end":50}}</tool>
<tool name="write_file" path="main.py"><content>print("hello")</content></tool>
<final>任务完成。</final>
```

Claude Code 用 LLM 的 tool use / function calling API，模型原生输出结构化工具调用。

后果：iatcoder 对接任何文本模型都可行（包括本地模型），但解析容错性较低；Claude Code 解析可靠但绑定 Anthropic。

#### 2. 记忆策略不同

iatcoder 的"dream"机制是独有的：

- 日常操作写入 `daily log`（`memory/logs/2026-06-09.md`）
- `/dream` 命令让模型阅读近期的 logs，将知识点归类写入 `memory/topics/` 下的分类文件（project-conventions.md、key-decisions.md 等）
- 下次 session 时，topic 文件会自动注入 prompt 作为上下文

Claude Code 的模式更轻量：

- `/compact` 压缩当前对话历史
- `CLAUDE.md` 文件持久化项目级指令
- 无显式的日志→主题整合管道

#### 3. 安全沙箱不同

iatcoder 通过 `features/sandbox/` 集成了 **bubblewrap** 沙箱支持，可以在受限环境中执行 shell 命令。同时有 shell env allowlist 和环境变量脱敏。

Claude Code 的安全模型基于权限等级（allow/deny/ask-by-default），无操作系统级沙箱。

#### 4. 工具协议差异

iatcoder 的所有工具通过 `tools/registry.py` 注册，每个工具有 schema、risk 标记、read_only 标记。`ToolProfile` 控制不同模式下可见的工具集。

Claude Code 使用 MCP（Model Context Protocol）扩展工具集，通过外部 MCP 服务器提供自定义工具。

### 总结

iatcoder 是一个**本地优先、provider 无关的 ReAct coding agent**，核心差异在于纯文本协议（可对接任意模型）、双层记忆 + dream 整合、可选 plan 模式、以及内置的 worker 子 agent 系统。相比 Claude Code，它更轻量、更开放、可自托管，但在协议稳健性和产品完成度上不如 Claude Code。

---

## Q3: iatcoder 支持两类模型后端，是哪两类？有什么区别？

iatcoder 通过 `providers/` 模块抽象了两类模型后端，分别对应 OpenAI 和 Anthropic 的 API 协议。第三方的 DeepSeek 实际上走的是 Anthropic 协议通道。

### 两类客户端

| 维度 | `OpenAICompatibleModelClient` | `AnthropicCompatibleModelClient` |
|------|------------------------------|----------------------------------|
| **API 端点** | `POST /v1/responses` | `POST /v1/messages` |
| **请求结构** | `{"input": [{"role":"user","content":[{"type":"input_text","text":...}]}]}` | `{"messages": [{"role":"user","content":[{"type":"text","text":...}]}]}` |
| **认证方式** | `Authorization: Bearer <api_key>` | `x-api-key: <api_key>` 请求头 |
| **响应提取** | 支持 JSON 和 SSE 两种格式 | 仅 JSON，固定 `content[].text` 结构 |
| **Prompt Cache** | 支持（对 `openai.com` 和 `right.codes` 开启） | 不支持（`supports_prompt_cache = False`） |
| **实现的协议** | OpenAI Responses API | Anthropic Messages API |
| **配置中的协议名** | `protocol = "openai"` | `protocol = "anthropic"` |
| **默认 max_tokens** | 8192 | 32000 |

### 请求结构差异

OpenAI 兼容格式（[clients.py:324](iatcoder/providers/clients.py#L324)）：
```python
payload = {
    "model": self.model,
    "input": [{
        "role": "user",
        "content": [{"type": "input_text", "text": prompt}],
    }],
    "max_output_tokens": max_new_tokens,
}
```

Anthropic 兼容格式（[clients.py:474](iatcoder/providers/clients.py#L474)）：
```python
payload = {
    "model": self.model,
    "messages": [{
        "role": "user",
        "content": [{"type": "text", "text": prompt}],
    }],
    "max_tokens": max_new_tokens,
}
```

### 响应提取差异

OpenAI 后端的响应格式变化较多，需要兼容多种变体：
- 普通 JSON 响应的 `choices[].message.content`
- SSE 流式响应的 `response.output_text.delta` / `response.output_text.done`
- Responses API 的 `output[].content[].text` 和 `output_text`
- 见 `_extract_openai_text()` 和 `_extract_openai_response_from_sse()`（[clients.py:29](iatcoder/providers/clients.py#L29)）

Anthropic 后端的响应结构固定，提取简单：
- 固定路径 `data.content[].text`，其中 `type == "text"`
- 见 `_extract_anthropic_text()`（[clients.py:449](iatcoder/providers/clients.py#L449)）

### Provider 发现与配置

配置的来源优先级（[config/__init__.py](iatcoder/config/__init__.py)）：
1. CLI 参数（`--model`, `--base-url`, `--api-key`）
2. 环境变量（`IATCODER_MODEL`, `IATCODER_BASE_URL`, `IATCODER_API_KEY`）
3. Provider 专属环境变量（`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`）
4. 项目 `.iatcoder.toml` 中的 `[providers.<name>]` 段
5. 用户级 `~/.config/iatcoder/config.toml`
6. 内置默认值

支持三种 provider 名称：`openai`、`anthropic`、`deepseek`。其中 `deepseek` 的协议默认为 `anthropic`（因为 DeepSeek 兼容 Anthropic 的 Messages API 格式）。

---

## Q4: iatcoder 调用模型后端时利用了 prompt cache 吗？如何做的？

**是的，但只对 OpenAI 兼容后端启用，且只缓存稳定前缀部分。**

### 设计思路

iatcoder 的 prompt 由两部分组成：
- **稳定前缀**（prefix）：系统身份、工具清单、调用规范、工作区快照 —— **跨轮次基本不变**
- **动态部分**：历史对话、记忆、当前用户请求 —— **每轮都变**

缓存策略的核心洞察是：只缓存稳定段，动态段每轮变化但不会使前缀缓存失效。

### 全链路实现

#### 第一步：检测后端是否支持（[clients.py:303](iatcoder/providers/clients.py#L303)）

```python
class OpenAICompatibleModelClient:
    def __init__(self, ...):
        self.supports_prompt_cache = any(
            host in self.base_url for host in ("openai.com", "right.codes")
        )
```

只对已知支持 prompt cache 语义的主机开启。Anthropic 客户端硬编码为 `False`。

#### 第二步：生成缓存键（[runtime.py:677](iatcoder/core/runtime.py#L677)）

```python
# _build_prompt_and_metadata() 中：
"prompt_cache_key": self.prefix_state.hash,
```

缓存键是 prefix 的 SHA256 哈希。只有当 workspace 变化导致 prefix 重建时，哈希才会改变，缓存才会失效。

#### 第三步：运行时传递缓存参数（[engine.py:241-255](iatcoder/core/engine.py#L241)）

```python
prompt_cache_key = None
prompt_cache_retention = None
if getattr(agent.model_client, "supports_prompt_cache", False):
    prompt_cache_key = prompt_metadata.get("prompt_cache_key")
    prompt_cache_retention = "in_memory"

result = complete_model(
    agent.model_client, prompt, agent.max_new_tokens,
    prompt_cache_key=prompt_cache_key,
    prompt_cache_retention=prompt_cache_retention,
)
```

#### 第四步：客户端发送缓存参数（[clients.py:344-347](iatcoder/providers/clients.py#L344)）

```python
if self.supports_prompt_cache and prompt_cache_key:
    payload["prompt_cache_key"] = prompt_cache_key
if self.supports_prompt_cache and prompt_cache_retention:
    payload["prompt_cache_retention"] = prompt_cache_retention
```

Anthropic 客户端则直接丢弃缓存参数（[clients.py:472](iatcoder/providers/clients.py#L472)）：
```python
def complete(self, prompt, max_new_tokens, prompt_cache_key=None, prompt_cache_retention=None):
    del prompt_cache_key, prompt_cache_retention  # 忽略缓存参数
```

#### 第五步：提取缓存命中信息（[clients.py:150-164](iatcoder/providers/clients.py#L150)）

```python
def _extract_usage_cache_details(data):
    usage = data.get("usage") or {}
    input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached_tokens = int(input_details.get("cached_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "cache_hit": cached_tokens > 0,
    }
```

这个信息流经 `last_completion_metadata` → `prompt_metadata` → `trace.jsonl` → `report.json`，用于分析缓存命中率。

#### 第六步：prefix 刷新策略（[runtime.py:539](iatcoder/core/runtime.py#L539)）

```python
def refresh_prefix(self, force=False):
    refreshed_workspace = WorkspaceContext.build(self.root)
    workspace_changed = (
        force or refreshed_workspace.fingerprint() != previous_workspace_fingerprint
    )
    prefix_state = (
        self.build_prefix() if workspace_changed or force or previous_hash is None
        else self.prefix_state
    )
```

只要 workspace fingerprint 没变，prefix 哈希就不变，prompt cache 就可以跨轮复用。这里的"轮"指的是同一 session 内连续的 `run_turn()` 迭代。

### 整体数据流

```
runtime.py (生成 cache key = prefix.hash)
      │
      ▼
engine.py (检测 supports_prompt_cache, 传递 key)
      │
      ▼
clients.py (把 key 写入 HTTP payload)
      │
      ▼
Provider API (缓存命中则节约 input tokens)
      │
      ▼
clients.py (从响应提取 cached_tokens)
      │
      ▼
last_completion_metadata → trace.jsonl (可观测)
```

### 注意事项

- Anthropic 客户端虽然不支持 prompt cache，但 `complete_model()` 统一调用接口（[base.py](iatcoder/providers/base.py)）对 runtime 透明——runtime 不需要知道后端是否支持缓存
- `complete_model()` 函数支持可选的 `complete_result` 方法，优先使用，否则回退到标准的 `complete()` + `last_completion_metadata` 模式
- prompt cache 的启用受 feature flag `"prompt_cache": True` 控制（[runtime.py:59](iatcoder/core/runtime.py#L59)），默认开启

---

## Q5: 会话（Session）、检查点（Checkpoint）、运行工件（Run Artifact）之间是如何建立对应关系并互相作用的？

iatcoder 有三层存储，分别服务于不同的生命周期和目的：

| 概念 | 存储位置 | 生命周期 | 目的 |
|------|----------|----------|------|
| **Session** | `.iatcoder/sessions/<id>.json` + `.events.jsonl` | 整个交互会话（多个用户请求） | 保存可恢复的对话状态 |
| **Checkpoint** | session JSON 内部 `checkpoints.items` | 单次 run 的各个阶段 | 记录进度用于 resume 续接 |
| **Run** | `.iatcoder/runs/<run_id>/`（task_state.json, trace.jsonl, report.json） | 一次 `ask()` 调用 | 审计和复盘 |

### 磁盘结构

```
.iatcoder/
├── sessions/
│   ├── 20260609-103000-abc123.json       # session 数据（含 checkpoints）
│   └── 20260609-103000-abc123.events.jsonl  # session 事件流
├── runs/
│   └── run_20260609-103000-def456/       # 一次 ask() 的运行证据
│       ├── task_state.json               #   状态机快照（不断更新）
│       ├── trace.jsonl                   #   流式事件序列（追加写入）
│       ├── report.json                   #   运行结束后的最终报告
│       └── artifacts/                    #   工具输出的完整内容归档
│           └── shell-output-001.txt
└── memory/                               # 持久记忆（独立于 session/run）
    ├── logs/2026/06/2026-06-09.md
    ├── topics/project-conventions.md
    └── MEMORY.md
```

### 对应关系

```
1 个 Session
  ├── 多次 user request
  │     └── 每次 → 1 个 Run（一次 ask()）
  │           ├── 1 个 TaskState（运行中不断更新 task_state.json）
  │           ├── 多个 Trace Event（追加写入 trace.jsonl）
  │           ├── 多个 Checkpoint（记录在 session JSON 中）
  │           │     └── 形成链表：checkpoint → parent → grandparent → ...
  │           └── 1 个 Report（运行结束时写入 report.json）
  └── 1 个 SessionEventBus（独立于 run 的事件流）
```

### 三者的生命周期与相互作用

#### 1. Session 的创建与持久化

Session 在 `Iatcoder.__init__()` 中创建（[runtime.py:162](iatcoder/core/runtime.py#L162)）：

```python
self.session = {
    "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
    "history": [],
    "memory": default_memory_state(),
    "checkpoints": {"current_id": "", "items": {}},
    "runtime_mode": {"mode": "default"},
    ...
}
```

每次 `record()` 调用都会通过 `SessionStore.save()` 原子写入磁盘（[session_store.py:30](iatcoder/core/session_store.py#L30)）。session JSON 是**完整快照**——包含全部 history、memory、checkpoints。

同时，`SessionEventBus` 将 session 级别的粗粒度事件（session_started、model_requested、tool_executed、assistant_message 等）追加写入 `.events.jsonl`（[session_events.py](iatcoder/core/session_events.py)）。

#### 2. Run 的启动与运行

每次用户请求（`Engine.run_turn()`）启动一个新 Run（[engine.py:92-104](iatcoder/core/engine.py#L92)）：

```python
task_state = TaskState.create(
    run_id=agent.new_run_id(),      # → "run_20260609-103000-def456"
    task_id=agent.new_task_id(),    # → "task_20260609-103000-ghi789"
    user_request=user_message,
)
agent.current_run_dir = agent.run_store.start_run(task_state)
# → 创建 .iatcoder/runs/run_20260609-103000-def456/ 目录
# → 写入初始 task_state.json
```

Run 的证据是三层文件：

1. **task_state.json** — 运行中持续更新的状态机（[task_state.py](iatcoder/core/task_state.py#L25)）
   ```
   run_id / task_id / status / tool_steps / attempts / last_tool /
   stop_reason / final_answer / checkpoint_id / changed_paths / ...
   ```
   每次工具调用、每次尝试都 `write_task_state()` 覆盖写入。

2. **trace.jsonl** — 流式事件序列，每行一个 JSON 事件（[runtime_events.py](iatcoder/core/runtime_events.py)）
   ```
   run_started / prompt_built / model_requested / model_parsed /
   tool_executed / checkpoint_created / run_finished / ...
   ```
   每个事件带 span_id → parent_span_id，形成调用链。

3. **report.json** — 运行结束时的最终摘要（[runtime.py:916](iatcoder/core/runtime.py#L916)）
   - 包含 task_state + prompt_metadata + durable_promotions + todo_changes + workers 等

#### 3. Checkpoint 的创建与链式结构

Checkpoint 在关键节点创建（[runtime_checkpoints.py:49](iatcoder/core/runtime_checkpoints.py#L49)），每个 checkpoint 包含：

```python
checkpoint = {
    "checkpoint_id": "ckpt_a1b2c3d4",
    "parent_checkpoint_id": "ckpt_e5f6g7h8",    # 形成链表
    "schema_version": "phase1-v1",
    "created_at": "...",
    "current_goal": "把 README 里的 Quick Start 段改成实际命令",
    "completed": ["已修改 README.md"],
    "current_blocker": "",
    "next_step": "运行测试验证修改正确",
    "key_files": [{"path": "README.md", "freshness": "sha256:..."}],
    "runtime_identity": {...},  # session_id / model / cwd / approval_policy 等
    "summary": "tool_executed: ...",
}
```

Checkpoint 的创建时机（`trigger`）：

| 触发条件 | 位置 | 含义 |
|----------|------|------|
| `tool_executed` | 每次工具执行后（engine_helpers.py:70） | 最频繁，每步都保存 |
| `run_finished` | 正常完成（engine.py:424） | 最终状态 |
| `aborted` / `step_limit_reached` / `retry_limit_reached` | finish helpers | 非正常结束 |
| `freshness_mismatch` | 检测到文件过期（engine.py:167） | 文件变更后首次启动 |
| `workspace_mismatch` | 运行时配置变化（engine.py:192） | model/approval 变化 |
| `context_reduction` | prompt 超预算被压缩（engine.py:204） | 预算压缩见证 |

Checkpoint 的**链式结构**使恢复时可以回溯：
```
ckpt_a (tool_executed: read_file)
  └→ ckpt_b (tool_executed: patch_file)
       └→ ckpt_c (tool_executed: run_shell)
            └→ ckpt_d (run_finished)
```

#### 4. Resume 续接：三个概念如何协作

当用户执行 `/resume <session_id>` 时（[session_lifecycle.py:14](iatcoder/core/session_lifecycle.py#L14)）：

```
resume_runtime_session()
  │
  ├── 1. shutdown_workers()       # 关闭旧 worker 线程
  │
  ├── 2. session_store.load()     # 加载 session JSON（含 checkpoints）
  │
  ├── 3. _rebind():               # 重建所有运行时子系统
  │     ├── SessionEventBus（绑定新 session_id）
  │     ├── LayeredMemory（从 session 恢复记忆）
  │     ├── TodoLedger / WorkerManager
  │     └── evaluate_resume_state()
  │           │
  │           ├── invalidate_stale_memory()
  │           │     → 检查工作记忆中的文件摘要是否过期
  │           │
  │           ├── current_checkpoint() → 取最新 checkpoint
  │           │     │
  │           │     ├── 比较 key_files.freshness 与当前文件哈希
  │           │     │     → 若有变化 → partial_stale
  │           │     │
  │           │     ├── 比较 saved runtime_identity 与当前
  │           │     │     → 若 model/cwd/approval 变了 → workspace_mismatch
  │           │     │
  │           │     └── 检查 schema_version
  │           │           → 若不匹配 → schema_mismatch
  │           │
  │           └── 返回 resume_status:
  │                 full_valid       ✓ 可安全续接
  │                 partial_stale    ⚠ 某些文件已变
  │                 workspace_mismatch ⚠ 运行时配置变了
  │                 schema_mismatch   ✗ checkpoint 格式不兼容
  │                 no_checkpoint    - 无 checkpoint
  │
  └── 4. 用户发送"继续" → Engine.run_turn()
        → prompt 中包含 render_checkpoint_text()
        → 模型可见: current_goal / completed / next_step / key_files / stale_paths
```

#### 5. 关键设计决策

**Checkpoint 放在 session 内而非 run 内**：checkpoint 的目的是"恢复对话"，而不是"审计某次运行"。它们跟对话历史一起存，恢复 session 时自然带上全部 checkpoint 链。相比之下，run 工件（trace/report）是只读审计日志，恢复时不需要它们。

**Run 证据是 append-only**：trace.jsonl 追加写入，即使进程崩溃也不会丢失已发生的事件。task_state.json 覆盖写入，但最终 report.json 会捕获最终状态。

**Session 是完整快照而非增量日志**：每次 `record()` 都写完整 session JSON。这是有意为之——session 文件通常很小（几十 KB），完整快照恢复逻辑简单，不存在事件回放的不确定性。

**Run 目录以 `run_id` 命名**：run_id 是 `run_20260609-103000-def456` 格式，包含时间戳，天然按时间排序。RunStore 提供 `load_task_state()` 和 `load_report()` 用于离线复盘，`evaluation/` 模块通过 `run_evidence.py` 读取这些工件进行评估。

**Session id 防路径穿越**（[session_store.py:96](iatcoder/core/session_store.py#L96)）：`_safe_session_id()` 检查 `/`、`\`、`.` 等路径穿越字符，确保 `/resume ../../etc/passwd` 这类攻击被拒绝。

---

## Q6: 这个项目是怎么处理各种失败的？对工具层做了怎样的设计？有幂等校验吗？

### 失败处理全景

iatcoder 的失败处理分五个层次，每层有不同的恢复策略：

```
模型调用失败          工具执行失败          格式错误          权限拒绝          step 超限
  │                    │                    │                │                │
  ├─ 网络/HTTP         ├─ 6 道关卡拦截      ├─ retry          ├─ 明确错误      ├─ step-limit
  │  自动重试 1 次     │  返回错误文本       │  最多 2 次      │  返回原因      │  摘要请求
  ├─ empty_response    ├─ 异常捕获          │                 │                │
  │  自动重试 1 次     │  partial_success   │                 │                │
  ├─ prompt_too_long   │  / error 分类      │                 │                │
  │  用户友好提示      │                    │                 │                │
  └─ 其他错误          └─ checkpoint         └─ 记录到 history  └─ process_note  └─ checkpoint
      用户友好提示        创建，可 resume
```

#### 层次一：Provider/网络错误（[engine.py:249-301](iatcoder/core/engine.py#L249)）

模型调用失败是最高优先级的错误处理：

```python
try:
    result = complete_model(agent.model_client, prompt, ...)
except Exception as exc:
    if should_retry_model_error(exc, provider_retries):
        provider_retries[code] += 1
        continue  # 重试
    yield from finish_model_error(...)
    return
```

重试策略（[engine_helpers.py:195](iatcoder/core/engine_helpers.py#L195)）：
- `empty_response`：最多重试 **1 次**
- HTTP 408/429/500/502/503/504+：`_request_with_retries()` 中自动重试（最多 2 次额外尝试）
- `auth_error` / `invalid_json` / `provider_error`：**不重试**，直接报错

错误信息对用户友好（[model_errors.py:15](iatcoder/core/model_errors.py#L15)）：
```python
if code == "empty_response":
    final = "模型返回空响应。可能原因：max_new_tokens 太小..."
elif code in {"prompt_too_long", "context_length_exceeded"}:
    final = "Prompt 超出模型上下文窗口。建议：/compact 压缩历史..."
else:
    final = f"模型错误：{code}..."
```

#### 层次二：模型输出格式错误（[model_output.py:37](iatcoder/core/model_output.py#L37)）

模型输出不是合法的 `<tool>` 或 `<final>` 时 → `kind="retry"`：

```python
if not raw.strip():
    return "retry", retry_notice("empty response")
return "retry", retry_notice("missing <tool> or <final> tag")
```

Engine 收到 retry 后（[engine.py:370-384](iatcoder/core/engine.py#L370)）：
- 将 retry 提示注入 history
- 不消耗 tool_steps（只算 attempts）
- 超出 `max_attempts = max_steps + 2` 则 `stop_retry_limit`

#### 层次三：工具执行错误（[tool_executor.py](iatcoder/core/tool_executor.py)）

工具失败分四种级别：

| 级别 | 条件 | `tool_status` | `tool_error_code` |
|------|------|---------------|-------------------|
| OK | 执行成功 | `ok` | `""` |
| Partial Success | shell 退出码 ≠ 0 但改了文件 | `partial_success` | `tool_partial_success` |
| Error | shell 退出码 ≠ 0 且未改文件 | `error` | `tool_failed` |
| Rejected | 被 6 道关卡拦截 | `rejected` | 见各关卡 |
| Exception | 执行中抛异常 | `partial_success` 或 `error` | `tool_partial_success` / `tool_failed` |

Partial Success 是很重要的设计（[tool_executor.py:111-119](iatcoder/core/tool_executor.py#L111)）：
```python
if exit_code != 0 and workspace_changed:
    tool_status = "partial_success"  # 命令失败了但改了文件
elif exit_code != 0:
    tool_status = "error"            # 纯失败，无副作用
```

执行中的异常捕获（[tool_executor.py:135-152](iatcoder/core/tool_executor.py#L135)）：
```python
except Exception as exc:
    after_snapshot = agent.capture_workspace_snapshot()  # 仍做 diff
    if workspace_changed:
        tool_status = "partial_success"
    else:
        tool_status = "error"
```

每个工具执行后立即创建 checkpoint（[engine_helpers.py:70](iatcoder/core/engine_helpers.py#L70)），确保即使后续步骤失败也能 resume。

#### 层次四：权限拒绝（[permissions.py](iatcoder/core/permissions.py)）

`PermissionChecker` 拦截四种情况：

```python
if not profile.allows(tool.name):
    deny("plan_mode_tool_not_allowed")
if read_only:
    deny("approval_denied")
if approval_policy == "never":
    deny("approval_denied")
if write_scope_mismatch:
    deny("write_scope_mismatch")
```

拒绝信息通过 `record_process_note_for_tool()` 写入工作记忆（[runtime.py:824](iatcoder/core/runtime.py#L824)）：
```python
def record_process_note_for_tool(self, name, metadata):
    status = metadata.get("tool_status", "")
    if status not in {"partial_success", "error", "rejected"}:
        return
    self.memory.append_note(text, tags=("process", status, ...), source=name, kind="process")
```

#### 层次五：Step 超限（[engine.py:472-491](iatcoder/core/engine.py#L472)）

当 `tool_steps >= max_steps` 时，Engine 先尝试让模型自己写一份进展摘要：

```python
summary = request_step_limit_summary(self, task_state, user_message)
if summary:
    final = summary + "\n\n— 已达本轮 step 预算上限（max_steps）。以上是当前进展总结。继续工作：/resume..."
else:
    final = "Stopped after reaching the step limit without a final answer."
```

这个摘要请求本身也是一次模型调用，让模型"不要继续执行工具，只汇报你做了什么以及还剩什么"。

### 工具层设计

#### 注册式架构（[tools/registry.py](iatcoder/tools/registry.py)）

工具是**显式注册**的，不是动态发现的：

```python
def build_tool_registry(agent):
    tools = {
        name: RegisteredTool(
            name=name,
            schema=spec["schema"],
            description=spec["description"],
            risky=bool(spec["risky"]),
            runner=partial(runner, agent),
        )
        for name, spec in BASE_TOOL_SPECS.items()
    }
    return tools
```

每个工具在 `BASE_TOOL_SPECS` 中定义三个属性：

```python
"read_file": {
    "schema": {"path": "str", "start": "int=1", "end": "int=200"},
    "risky": False,
    "description": "Read a UTF-8 file by line range.",
}
"write_file": {
    "schema": {"path": "str", "content": "str"},
    "risky": True,
    "description": "Write a text file.",
}
```

#### 六道关卡守卫（[tool_executor.py:20](iatcoder/core/tool_executor.py#L20)）

```
                     ┌─────────────────────────────┐
                     │  模型输出 <tool>...</tool>    │
                     └─────────────┬───────────────┘
                                   ▼
                    [1]  工具是否存在？──── 不存在 → unknown_tool
                                   │
                                   ▼
                    [2]  参数是否合法？──── 非法 → invalid_arguments
                     （含路径逃逸检测）         （附正确示例）
                                   │
                                   ▼
                    [3]  是否重复调用？──── 重复 → repeated_identical_call
                                   │
                                   ▼
                    [4]  PermissionChecker ── 拒绝 → tool_not_allowed /
                       approval/plan_mode/         approval_denied /
                       write_scope/read_only       plan_mode_path_mismatch
                                   │
                                   ▼
                    [5]  ToolPolicyChecker ── 拒绝 → prior_read_required /
                       先读后写/shell搜索禁          shell_search_should_use_tool
                                   │
                                   ▼
                    [6]  执行 → snapshot before → run
                          → snapshot after → diff → 更新记忆
                                   │
                          ┌────────┴────────┐
                          ▼                  ▼
                      exit_code=0        exit_code≠0
                      tool_status=ok     partial_success / error
                          │                  │
                          └─────── 都创建 checkpoint
```

**关键细节：参数校验**（`validate_tool` 在 `registry.py:115`）

每个工具有独立的参数校验逻辑：

- `patch_file`：`old_text` 必须在文件中**恰好出现一次**（registry.py:170），防止模糊替换
- `run_shell`：timeout 限制在 1–120 秒（registry.py:146）
- `write_file`：如果路径已存在且是目录则拒绝（registry.py:152）
- 路径参数统一通过 `agent.path()` 校验，确保不逃逸 workspace（runtime.py:996）

**关键细节：结果裁剪与归档**（[tool_executor.py:155](iatcoder/core/tool_executor.py#L155)）

```python
def _render_tool_result(agent, name, full_result):
    if name != "run_shell" or len(full_result) <= INLINE_TOOL_OUTPUT_LIMIT:
        return clip(full_result), ""
    path = agent.run_store.write_text_artifact(..., f"{name}-output", full_result)
    return f"full output saved: {relative}\n" + clip(full_result, 1000), relative
```

**关键细节：Sandbox 集成**（[registry.py:272](iatcoder/tools/registry.py#L272)）

`run_shell` 支持通过 `sandbox_runner` 在 bubblewrap 沙箱中执行命令。

### 幂等校验（重复调用检测）

**有，在关卡 [3]。** 核心实现在 [tool_repetition.py](iatcoder/core/tool_repetition.py)。

#### 普通工具的幂等规则

```python
def is_repeated_tool_call(history, name, args):
    current_turn = _current_turn_history(history)
    matches = [ ...相同 name + 相同 args... ]
    if name in FILE_MUTATION_TOOLS:
        # 特殊规则（见下文）
    return len(matches) >= 2
```

即：**同一 turn 内，相同的工具名 + 完全相同的参数，第二次就会被拦截。**

#### 写文件的智能幂等规则

`write_file` 和 `patch_file` 有特殊逻辑：

```python
if name in FILE_MUTATION_TOOLS:
    if not matches:
        return False
    last_index, last_match = matches[-1]
    return not _failed_file_write_retry_is_now_informed(..., last_match)
```

`_failed_file_write_retry_is_now_informed()` 的判断逻辑（[tool_repetition.py:44](iatcoder/core/tool_repetition.py#L44)）：
1. 上一次相同的 `write_file`/`patch_file` 结果以 `"error:"` 开头（被拒绝）
2. 拒绝之后，模型对该路径做了一次成功的 `read_file`
3. → 判定为"合理的失败重试"，**放行**

#### 幂等校验的范围

- 只检查**当前 turn**，不跨 turn
- 参数必须**完全相等**（Python 字典比较）
- 检测到重复时，`tool_error_code = "repeated_identical_call"`，错误文本提示"换一个工具或返回 final"

---

## Q7: 项目支持动作的回滚吗？

**不支持自动回滚。项目有完备的变更检测机制，但只用于审计和 resume 提示，不提供文件级撤销能力。**

### 现有机制：变更检测（detect only）

每次 risky tool 执行前后，`tool_executor.py` 的第六道关卡会捕获工作区快照并进行 diff（[tool_executor.py:101-107](iatcoder/core/tool_executor.py#L101)）：

```python
before_snapshot = agent.capture_workspace_snapshot() if tool.risky else {}
result = tool.execute(args).content
after_snapshot = agent.capture_workspace_snapshot() if tool.risky else before_snapshot
affected_paths, diff_summary = agent.diff_workspace_snapshots(before_snapshot, after_snapshot)
```

快照是**哈希字典**（[runtime_checkpoints.py:16](iatcoder/core/runtime_checkpoints.py#L16)）：

```python
def capture_workspace_snapshot(self):
    snapshot = {}
    for path in self.root.rglob("*"):
        ...
        snapshot[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot
```

diff 结果只输出变更摘要：

```python
def diff_workspace_snapshots(before, after):
    for path in sorted(set(before) | set(after)):
        if before.get(path) == after.get(path):
            continue
        summaries.append(f"created:{path}" if path not in before
            else f"deleted:{path}" if path not in after
            else f"modified:{path}")
    return changed_paths, summaries
```

这个 diff 信息的流向：

```
tool_executor
  ├──→ agent._last_tool_result_metadata["diff_summary"]（给 trace）
  ├──→ agent._last_tool_result_metadata["affected_paths"]（给 report）
  └──→ checkpoint["freshness"]（给 resume 判断 stale）
```

### 为什么不做回滚

从代码中可以看出几个设计决策：

1. **快照只存哈希，不存文件内容**：SHA256 哈希可以告诉你"README.md 变了"，但无法恢复修改前的内容。要支持回滚需要完整的文件内容备份，存储和性能成本都高得多。

2. **patch_file 的自身约束减少了回滚需求**：`patch_file` 要求 `old_text` **精确匹配且在文件中恰好出现一次**（[registry.py:170](iatcoder/tools/registry.py#L170)）。这本身就是一种"可视化的回滚凭证"——你永远知道被替换掉的原文是什么，可以手动或通过新工具调用来恢复。

3. **依赖 git 做回滚**：项目鼓励在 git 仓库中使用（`WorkspaceContext` 自动检测 git 信息），模型可以运行 `git diff`、`git checkout`、`git restore` 等命令来撤销变更，这些通过 `run_shell` 工具可被模型自主调用。

4. **checkpoint 不是文件级快照**：checkpoint 保存的是"任务进展到什么程度了"（current_goal、completed、next_step 等语义信息），而不是文件内容的物理备份。它能让 agent 理解上下文续接，但无法撤销物理变更。

### 如果要实现回滚需要什么

在现有架构上，如果要支持真正的回滚，需要三个增量：

```
增量 1：capture_workspace_snapshot()
       └→ 存 SHA256 哈希 → 改为存文件副本到 run_dir/artifacts/

增量 2：新增 tool_rollback 工具
       └→ 读取 run_dir/artifacts/ 中的备份 → 写回原路径

增量 3：checkpoint 关联 artifact 目录
       └→ 每个 checkpoint 记录对应的 artifact 备份 ID
```

但到目前为止，项目没有实现这些——失败处理策略是"创建 checkpoint → resume 时告知模型什么文件变了 → 模型自行决定如何继续"，而不是"检测失败 → 自动撤销已执行的变更"。

---

## Q8: 沙箱是怎么设计的？什么场景用的？

iatcoder 通过 `features/sandbox/` 模块集成了 **bubblewrap** 沙箱支持，用于在受限环境中执行 shell 命令，隔离潜在的危险操作。

### 沙箱配置

[SandboxConfig](iatcoder/features/sandbox/config.py) 是一个 frozen dataclass：

```python
@dataclass(frozen=True)
class SandboxConfig:
    mode: str = "off"            # off / best_effort / required
    backend: str = "auto"        # 目前仅 auto → bubblewrap
    workspace_write: bool = True # 是否允许 sandbox 内写 workspace
    excluded_commands: tuple[str, ...] = ()
    extra_readonly_paths: tuple[str, ...] = ()
    deny_read: tuple[str, ...] = ()
    deny_write: tuple[str, ...] = ()
```

三种模式：

| 模式 | 行为 |
|------|------|
| `off` | 不使用沙箱，直接执行 |
| `best_effort` | 优先使用沙箱，若 bwrap 不可用则回退到普通执行 |
| `required` | 强制使用沙箱，若 bwrap 不可用则抛出 `RuntimeError` |

### 运行决策逻辑

[SandboxRunner.run()](iatcoder/features/sandbox/runner.py) 的决策树：

```
SandboxRunner.run(command)
  │
  ├── mode == "off" → _plain()                 # 直接 subprocess.run
  │
  ├── mode != "required" AND 命令匹配 excluded_commands
  │     → _plain()                              # 被排除的命令不沙箱化
  │
  ├── 检查 bwrap 是否可用
  │     ├── 不可用 AND mode == "required"
  │     │     → raise RuntimeError("bwrap not available")
  │     ├── 不可用 AND mode == "best_effort"
  │     │     → _plain()                         # 静默回退
  │     └── 可用
  │           → _bubblewrap_argv(command)         # 构造 bwrap 参数
  │
  └── 执行 → subprocess.run(argv, ...)
```

### Bubblewrap 隔离策略

[_bubblewrap_argv()](iatcoder/features/sandbox/runner.py) 构造 bwrap 参数：

```
bwrap
  --ro-bind /usr /usr           # 只读系统目录
  --ro-bind /bin /bin
  --ro-bind /lib /lib
  --ro-bind /lib64 /lib64
  --ro-bind /etc /etc
  --proc /proc
  --dev /dev
  ...
  --ro-bind|cwd|cwd             # workspace 按 config.workspace_write 决定只读/读写
  --bind|tmpfs|deny_write_paths # 拒绝写入的路径挂载 tmpfs
  --dev-bind /dev/null /dev/null
  ...
  -- <command>
```

关键特性：
- 系统目录（/usr, /bin, /lib 等）以只读方式挂载
- 工作区目录根据 `workspace_write` 配置决定 bind（读写）或 ro-bind（只读）
- `deny_write` 路径挂载空 tmpfs，命令无法写入这些位置
- `deny_read` 路径同样挂载空 tmpfs，命令无法读取
- `extra_readonly_paths` 以只读方式额外挂载
- `excluded_commands` 使用 fnmatch 模式匹配，匹配的命令绕过沙箱

### 命令排除机制

[command_matcher.py](iatcoder/features/sandbox/command_matcher.py) 中的 `command_is_excluded()` 使用 fnmatch 匹配：

```python
def command_is_excluded(command, patterns):
    for pattern in patterns:
        if fnmatch.fnmatch(command, pattern):
            return True
    return False
```

被排除的命令（如 `pip install`、`npm install` 等可能安装大型依赖的命令）即使沙箱开启也直接执行，避免 bwrap 内的文件系统限制导致安装失败。

### 使用场景

1. **运行不受信任的代码**：从网上下载的脚本或在沙箱中执行
2. **隔离构建过程**：避免构建脚本意外污染系统文件
3. **防止误操作**：`deny_write` 配置可以保护关键路径不被 agent 意外修改
4. **安全审计**：`required` 模式确保所有 shell 命令都在沙箱中执行，提供完全的审计追踪

---

## Q9: 审批策略具体是什么？触发时机是什么？

### 策略定义

iatcoder 有三种审批策略，在配置中通过 `approval_policy` 字段设定：

| 策略 | 配置文件值 | 行为 |
|------|-----------|------|
| **auto** | `"auto"` | 自动审批低风险（read-only）工具，高风险（risky）工具自动放行，无需人工确认 |
| **ask** | `"ask"` | 每次 risky 工具调用前都询问用户是否允许 |
| **never** | `"never"` | 拒绝所有 risky 工具调用 |

默认值是 `"auto"`。

### 触发时机：六道关卡的第四道

审批检查触发于 [tool_executor.py](iatcoder/core/tool_executor.py) 的 guard 阶段，具体是关卡 [4] PermissionChecker：

```
[1] 工具是否存在？      → unknown_tool
[2] 参数是否合法？      → invalid_arguments（含路径逃逸检测）
[3] 是否重复调用？      → repeated_identical_call
[4] PermissionChecker → tool_not_allowed / approval_denied / write_scope_mismatch
[5] ToolPolicyChecker → prior_read_required / shell_search_should_use_tool
[6] 执行              → snapshot → run → snapshot → diff
```

### PermissionChecker 的检查链

[permissions.py](iatcoder/core/permissions.py) 中的检查顺序：

```python
# 1. Profile 限制（plan 模式下只能使用受限工具集）
if not profile.allows(tool.name):
    deny("plan_mode_tool_not_allowed")

# 2. Plan 模式写路径检查
if write_scope_mismatch:
    deny("write_scope_mismatch")

# 3. Read-only 模式限制
if read_only:
    deny("approval_denied")

# 4. 审批策略检查
if approval_policy == "never":
    deny("approval_denied")
```

最终调用 [runtime.py](iatcoder/core/runtime.py#L956) 的 `Iatcoder.approve()` 方法：

```python
def approve(self, tool_name, tool_args):
    if self.read_only:
        return False, "read_only mode"
    if self.approval_policy == "ask":
        return self.input_approval(tool_name, tool_args)
    if self.approval_policy == "never":
        return False, f"approval_policy is set to never"
    if self.approval_policy == "auto":
        return True, ""
    return True, ""
```

### 不同交互模式的审批体验

**REPL 模式**（[cli.py](iatcoder/cli.py)）：`input_approval()` 使用 `input()` 同步等待用户输入。

**TUI 模式**（[tui/app.py](iatcoder/tui/app.py#L310)）：`_approval_callback` 创建 `threading.Event`，通过 `call_from_thread()` 在 UI 线程显示 `ConfirmPrompt` 对话框，然后阻塞等待 Event 被 set：

```python
def _approval_callback(self, tool_name, tool_args):
    event = threading.Event()
    result = [False]

    def show():
        def on_confirm(approved):
            result[0] = approved
            event.set()
        self.call_from_thread(self._show_confirm, tool_name, tool_args, on_confirm)

    show()
    event.wait()
    return result[0], ""
```

### 拒绝后的处理

被拒绝的工具调用结果包含 `tool_status = "rejected"`，通过 `record_process_note_for_tool()` 写入工作记忆（[runtime.py:824](iatcoder/core/runtime.py#L824)）。模型在后续迭代中能看到拒绝原因并调整行为（例如改用 read-only 工具或直接返回 `<final>`）。

---

## Q10: 模型怎么从会话中提取持久化记忆的？

iatcoder 有两套记忆提取机制：一套是 **`<memory>` 标签**，模型可以在回答中显式标记需要记忆的内容；另一套是 **自动意图识别**，通过正则匹配用户消息和最终回答中的结构化内容。

### 层次一：显式 `<memory>` 标签

模型可以在回答中嵌入 `<memory>` 标签，标记需要持久化的信息（[memory.py:194](iatcoder/features/memory.py#L194)）：

```python
def extract_memory_tags(text):
    """从文本中提取 <memory>...</memory> 标签内容。"""
    return re.findall(r"<memory>(.*?)</memory>", text, flags=re.DOTALL)
```

例如模型输出：
```
<tool name="read_file" path="setup.py"><content>...</content></tool>
<memory>项目使用 setuptools 作为构建工具，Python 版本要求 >= 3.10</memory>
<final>已了解项目构建配置。</final>
```

这个 `extract_memory_tags()` 由 `maintain_memory_after_turn()` 调用（[memory.py:651](iatcoder/features/memory.py#L651)），**每次 turn 的 final answer 后都会执行**：

```python
def maintain_memory_after_turn(agent, final_answer):
    """每次 turn 结束后，从 final answer 提取记忆并维护 daily log。"""
    tags = extract_memory_tags(final_answer)
    if tags:
        for content in tags:
            agent.memory.add_daily_log(content, source="memory_tag")
    # 同时也记录到 daily log
    agent.memory.append_daily_log(...)
```

### 层次二：自动持久化意图识别

除了显式标签，系统会自动检测用户是否在"要求记住某事"（[memory.py:574](iatcoder/features/memory.py#L574)）：

**第一步：检测用户意图**

```python
DURABLE_MEMORY_INTENT_PATTERN = re.compile(
    r'\b(capture|remember|save|store|persist|note)\b', re.IGNORECASE
)
# 也支持中文
ZH_DURABLE_MEMORY_INTENT_PATTERN = re.compile(
    r'[记保][住录][住录]?|持久化|保存|存储|记住', ...
)
```

如果用户消息匹配这些模式，系统认为"用户在要求保存信息"。

**第二步：解析模型回答中的结构化内容**

```python
DURABLE_MEMORY_LINE_PATTERNS = [
    re.compile(r'^Project convention:\s*(.+)', re.IGNORECASE),
    re.compile(r'^Decision:\s*(.+)', re.IGNORECASE),
    re.compile(r'^Preference:\s*(.+)', re.IGNORECASE),
    re.compile(r'^项目约定[：:]\s*(.+)'),
    re.compile(r'^决策[：:]\s*(.+)'),
    # ...更多模式
]
```

从模型的 `<final>` 回答中逐行匹配这些模式，提取出需要持久化的知识点。

**第三步：写入 durable memory**

`promote_durable_memory()`（[memory.py:600](iatcoder/features/memory.py#L600)）将提取的内容实际写入记忆系统：

```python
def promote_durable_memory(agent, user_message, final_answer):
    """从对话中提取需要持久化的记忆。"""
    extracted = extract_durable_promotions(user_message, final_answer)
    if extracted:
        for item in extracted:
            agent.memory.promote_durable(item["content"], item.get("tags"))
```

在 [runtime.py](iatcoder/core/runtime.py) 中，`promote_durable_memory` 在 run 成功完成或 `stop_limited` 时被调用。

### 层次三：Dream 整合

以上两种机制产生的记忆条目会写入 `memory/logs/` 下的 daily log 文件。而 `/dream` 命令启动一个**子 agent** 读取近期的 daily logs，将零散的知识点归类为 `memory/topics/` 下的结构化主题文件：

```
memory/
├── logs/
│   └── 2026/06/
│       └── 2026-06-09.md      # 日常日志，包含 <memory> 标签和自动提取的内容
├── topics/
│   ├── project-conventions.md  # 项目约定
│   ├── key-decisions.md        # 关键决策
│   └── tech-stack.md           # 技术栈
└── MEMORY.md                   # 索引文件
```

下次 session 启动时，topic 文件会被注入 prompt 前缀，作为系统上下文的一部分。这就实现了跨 session 的持久化记忆。

### 触发时机总结

| 机制 | 触发时机 | 位置 |
|------|---------|------|
| `<memory>` 标签提取 | 每次 turn 的 final answer 后 | `maintain_memory_after_turn()` |
| 自动意图识别 | run 成功完成或 stop_limited 时 | `promote_durable_memory()` |
| Dream 整合 | 用户手动执行 `/dream` | `dream()` |

所有记忆提取都是**自动的**——用户不需要手动告诉系统"记住这个"，只要输出 `<memory>` 标签或自然语言中包含"记住/保存"等意图，系统就会处理。

---

## Q11: TUI 和 REPL 的区别是什么？一个请求进来，链路流程一样吗？

**核心链路完全相同**——两种模式共享同一个 `Engine.run_turn()` 生成器。区别在于事件分发方式和用户交互方式。

### 共享核心

两种模式共用完整的 ReAct 引擎：

```
请求 → Engine.run_turn() → [model → parse → tool → model → ... → final]
                                ↑ 同一套生成器，产生相同的 RuntimeEvent      │
                                └──────────────────────────────────────────┘
```

`Engine.run_turn()` 是一个生成器函数，每次 yield 一个 `RuntimeEvent`（[runtime_events.py](iatcoder/core/runtime_events.py)），事件类型包括：

- `model_requested` / `model_parsed`
- `tool_executed` / `tool_rejected`
- `checkpoint_created`
- `run_finished` 等

### REPL 模式

[cli.py](iatcoder/cli.py#L615) 中的同步循环：

```python
while True:
    text = input(prompt_str)      # 阻塞等待用户输入
    if text.startswith("/"):
        handle_repl_command(text)
    else:
        result = agent.ask(text)   # 同步调用，内部消费 run_turn() 生成器
        print(result)
```

- **同步阻塞**：`input()` 等待用户输入 → `agent.ask()` 同步执行直到完成
- **审批交互**：`input_approval()` 直接调用 `input()`，同步等待
- **工具结果**：直接打印在终端
- **无 UI 更新**：不需要事件分发到 UI 组件

### TUI 模式

[tui/app.py](iatcoder/tui/app.py#L190) 中的异步架构：

```python
async def _agent_task(self, text):
    """在 Textual 应用生命周期内运行 agent。"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, self._drive_turn, text)

def _drive_turn(self, text):
    """在后台线程中驱动 run_turn() 生成器。"""
    for event in engine.run_turn(text):     # 同步生成器
        self.call_from_thread(self._handle_runtime_event, event)  # 跨线程投递

def _handle_runtime_event(self, event):
    """在 UI 线程中处理事件，更新对应 widget。"""
    if isinstance(event, ToolExecuted):
        self._update_tool_card(event)
    elif isinstance(event, ModelRequested):
        self._update_thinking_indicator(event)
    # ...
```

**审批交互**使用 `threading.Event` 进行跨线程同步（[tui/app.py:310](iatcoder/tui/app.py#L310)）：

```python
def _approval_callback(self, tool_name, tool_args):
    event = threading.Event()
    result = [False]

    def show():
        self.call_from_thread(self._show_confirm_dialog, tool_name, tool_args,
            lambda approved: (result.__setitem__(0, approved), event.set()))

    show()
    event.wait()          # 阻塞后台线程
    return result[0], ""
```

### 对比总结

| 维度 | REPL | TUI |
|------|------|-----|
| **驱动方式** | 同步 `while True` 循环 | Textual async 事件循环 |
| **引擎调用** | `agent.ask()` 同步包装 | `loop.run_in_executor()` 在后台线程跑生成器 |
| **事件分发** | 不需要（引擎内部处理） | `call_from_thread()` 将事件分发到 UI widget |
| **审批交互** | `input()` 同步等待 | `threading.Event` + `call_from_thread()` 显示对话框 |
| **工具结果展示** | 原始文本打印 | ThinkingIndicator / ToolCard / ChatLog 等结构化 widget |
| **多行输入** | `/editor` 调外部编辑器 | 原生 TextArea widget |
| **文件** | cli.py | tui/app.py |

### 一句话总结

**引擎一样，分发不同。** `Engine.run_turn()` 的生成器事件流是一致的，REPL 直接消费结果文本，TUI 把每个事件解包后分发给 Textual widget 进行可视化渲染。请求的生命周期、工具执行、权限检查、记忆维护全部相同。

---

## Q12: 项目有没有子 Agent 的协作模式？怎么做的？和 Claude Code 的 subAgent / fork 模式有什么区别？

**有。iatcoder 的 WorkerManager 实现了两种子 agent 类型：`Explore`（只读调查）和 `worker`（受限写入）**，在概念上对标 Claude Code 的 Explore 和 Worker，但实现上有显著差异。

### 子 Agent 类型

两种类型由 `_clean_type()` 硬编码约束（[worker_manager.py:218](iatcoder/core/worker_manager.py#L218)）：

```python
def _clean_type(value):
    subagent_type = str(value or "worker").strip()
    if subagent_type not in {"worker", "Explore"}:
        raise ValueError("subagent_type must be worker or Explore")
    return subagent_type
```

| 维度 | Explore | Worker |
|------|---------|--------|
| **目的** | 只读调查/搜索 | 有写入范围的子任务 |
| **approval_policy** | `"never"`（拒绝所有写入） | `"auto"`（自动放行） |
| **read_only** | `True` | 取决于 write_scope 是否为空 |
| **tool_profile** | `"readonly"` | `"worker"` |
| **可用工具** | list_files, read_file, search, todo 操作 | 除 agent/send_message/task_stop/ask_user/plan_mode/run_shell 外的全部工具 |
| **write_scope** | 不需要（不能写） | 需要，指定可写入的路径范围 |
| **plan 模式下** | 允许 | 不允许 |

### 子 Agent 的创建：build_child_runtime()

[worker_runtime.py:9](iatcoder/core/worker_runtime.py#L9) 的 `build_child_runtime()` 为每个子 agent 创建一个**全新的 `Iatcoder` 实例**：

```python
def build_child_runtime(parent, subagent_type, write_scope):
    child = Iatcoder(
        root=parent.root,
        model_client=parent.model_client_factory(),
        approval_policy="never" if subagent_type == "Explore" else "auto",
        read_only=(subagent_type == "Explore" or not write_scope),
        tool_profile="readonly" if subagent_type == "Explore" else "worker",
        max_steps=parent.max_steps,
        max_new_tokens=parent.max_new_tokens,
        depth=parent.depth + 1,        # 防止递归
        write_scope=write_scope,
        sandbox_config=parent.sandbox_config,
        # ... 继承其他配置
    )
    child.refresh_prefix(force=True)
    return child
```

**继承自父 agent 的：**
- workspace 根路径
- session_store / run_store
- max_steps, max_new_tokens
- secret_env_names, shell_env_allowlist
- feature_flags, sandbox_config
- ask_user_callback

**子 agent 独有的：**
- **全新 session**（空 history、空 memory）—— 不继承父 agent 的对话历史
- **完整但不含子 agent 工具的 prompt prefix** —— 系统身份、工具清单（按 profile 过滤）、调用规范全部重建
- `depth = parent.depth + 1`，受 `max_depth`（默认 1）限制递归深度
- 独立的 `model_client`（通过 `model_client_factory()` 创建）或共享父 agent 的客户端

### 工具权限隔离

子 agent 的 tool profile 在 [tool_profiles.py](iatcoder/core/tool_profiles.py) 中定义。

**Explore 的 readonly 工具集**（[tool_profiles.py:25](iatcoder/core/tool_profiles.py#L25)）：

```python
readonly = frozenset(
    name for name, tool in tools.items() if tool.read_only
) - coordinator_tools - mode_tools - interactive_tools
# 结果：list_files, read_file, search, todo_add, todo_update, todo_list
```

**Worker 的受限工具集**（[tool_profiles.py:43](iatcoder/core/tool_profiles.py#L43)）：

```python
worker_tools = (all_tools - coordinator_tools - mode_tools - interactive_tools
                - frozenset({"run_shell"}))
# 结果：除 agent/send_message/task_stop/enter_plan_mode/exit_plan_mode/ask_user/run_shell 外的所有工具
```

关键约束：

| 约束 | 原因 |
|------|------|
| **不能递归生子 agent** | `agent` 工具在所有子 profile 中都被移除 |
| **不能执行 shell** | `run_shell` 从 worker profile 中移除（Explore 的 readonly 集本来就不包含） |
| **不能与用户交互** | `ask_user` 被移除 |
| **不能切换模式** | `enter_plan_mode` / `exit_plan_mode` 被移除 |
| **写入范围受限** | `write_scope` 在 PermissionChecker 中逐路径检查（[permissions.py:75](iatcoder/core/permissions.py#L75)） |

### 子 Agent 的执行模型

[worker_execution.py:13](iatcoder/core/worker_execution.py#L13) 的 `run_worker()`：

```python
def run_worker(manager, task, prompt, action="start"):
    task.state["status"] = "running"
    try:
        result = task.runtime.ask(str(prompt or ""))  # 完整 ReAct 循环
        task.state["status"] = "completed"
        task.state["result"] = clip(result, 2000)
    except Exception as exc:
        task.state["status"] = "failed"
        task.state["result"] = str(exc)
    # 收集工件路径
    collect_worker_artifacts(task)
    # 通知主 agent
    manager._notifications.put((task.id, notification))
```

**两种执行模式：**

1. **后台线程模式**（有 `model_client_factory`）：`spawn()` 返回 `status: "started"`，子 agent 在 daemon 线程中并发执行
2. **同步模式**（无 `model_client_factory`）：`spawn()` 阻塞直到子 agent 完成

主 agent 通过 `drain_notifications()` 在 Engine.run_turn() 的三个时机检查子 agent 结果：

```
Engine.run_turn() 循环
  ├── 每次模型调用前        → drain_worker_notifications()
  ├── 每次工具执行后        → drain_worker_notifications()
  └── 最终 yield final 前   → drain_worker_notifications()
```

### 通信机制：XML 通知注入

子 agent 完成时，结果被渲染为 XML（[worker_notifications.py](iatcoder/core/worker_notifications.py)）：

```xml
<task-notification>
  <task-id>agent_1</task-id>
  <status>completed</status>
  <summary>Agent Inspect README completed</summary>
  <result>README says demo readme.</result>
  <usage>
    <tool_uses>1</tool_uses>
    <attempts>1</attempts>
    <duration_ms>1234</duration_ms>
  </usage>
</task-notification>
```

这个 XML 被作为 `{"role": "user", "content": notification}` 注入主 agent 的 `session["history"]`（[engine.py:50](iatcoder/core/engine.py#L50)）。下一轮模型调用时，主 agent 在上下文中"看到"子 agent 的结果，就像收到一条用户消息。

### 三种工具控制子 Agent

主 agent 通过三个工具与子 agent 交互（[tools/agents.py](iatcoder/tools/agents.py)）：

| 工具 | 功能 |
|------|------|
| `agent` | 创建新的子 agent：`{"description": "...", "prompt": "...", "subagent_type": "Explore", "write_scope": []}` |
| `send_message` | 向运行中的子 agent 发送后续消息：`{"to": "agent_1", "message": "..."}` |
| `task_stop` | 停止子 agent：`{"task_id": "agent_1"}` |

子 agent 被停止时，`stop_task()` 调用 `task.runtime.abort_current_turn()`（[worker_manager.py:164](iatcoder/core/worker_manager.py#L164)），设置 `abort_requested` 标志并调用 `model_client.abort()`。

### 与 Claude Code 的对比

| 维度 | iatcoder | Claude Code |
|------|----------|-------------|
| **子 agent 类型** | 2 种：Explore + worker | 2 种：Explore + Worker |
| **进程模型** | daemon 线程（同一进程） | 独立子进程（进程级隔离） |
| **上下文继承** | 全新 session，完整 prefix，**不继承父 agent 历史** | Explore 用自定义搜索 prompt；Worker 继承部分上下文 |
| **工具限制** | Explore 纯只读；Worker 不能 run_shell、不能递归、不能 ask_user、不能 plan_mode | Explore 限制为 search/read；Worker 权限更多，可递归生子 agent |
| **写入隔离** | `write_scope` + `read_only` + `tool_profile` 三层检查 | 进程级文件系统隔离 |
| **递归限制** | 禁止（agent 工具从所有子 profile 移除） | 允许 Worker 递归 |
| **Shell 能力** | Worker **不能**执行 shell | Worker 可以执行 shell（有沙箱） |
| **通信** | XML 通知注入主 agent 历史 | 结构化 IPC 事件 |
| **结果收集** | 自动 drain，每次模型调用/工具执行后检查 | 事件驱动 |
| **生命周期** | 随 session 生命周期，clear/resume 时 shutdown | 随对话生命周期 |
| **并发** | 多 worker 可并行运行（各占一个线程和一个模型客户端） | 多 Worker 可并行 |
| **用户触发** | `/subagent explore <task>` / `/subagent worker --scope <path> <task>` | `/spawn` |

### 初始化与清理

WorkerManager 在 `Iatcoder.__init__()` 中创建（[runtime.py:191](iatcoder/core/runtime.py#L191)），在 session clear 或 resume 时 shutdown（[session_lifecycle.py](iatcoder/core/session_lifecycle.py)）：

```python
def _shutdown_workers(runtime):
    runtime.worker_manager.shutdown(timeout=2.0)
    runtime.worker_manager = WorkerManager(runtime)  # 重建
```

shutdown 会遍历所有 task，对运行中的设置 stop_requested，join 线程，超时 2 秒后未结束的线程将被遗弃。

### 设计决策总结

1. **线程而非进程**：子 agent 运行在同一进程的 daemon 线程中，没有进程级隔离，但共享内存和文件描述符，通信开销低
2. **无历史继承**：子 agent 从空白 session 开始，避免父 agent 上下文泄露和 token 浪费
3. **Worker 不能执行 shell**：这是刻意的安全决策——即使 write_scope 限制了文件写入范围，shell 命令可以轻易绕过（如 `cat > /some/other/path`），所以完全禁止
4. **XML 通知而非结构化数据**：与主协议一致（纯文本），让模型"读到"通知内容而不是处理结构化事件
5. **异步结果通过 drain 拉取**：非事件驱动，而是 Engine 循环主动检查通知队列，简单可靠
