# Iatcoder 简历指标溯源

> 所有数字分三类：(A) 代码静态数——直接数代码元素；(B) 实验设计——代码里定义了多少个测试用例/配置；(C) 实验结果——跑完实验得出的实际输出。

---

## 1. "2 类模型后端" — (A) 代码静态数

**文件**: `iatcoder/providers/clients.py`

代码中只有两个 client 类：

| 类 | 协议 | 序列化格式 | API 路径 | 缓存支持 |
|---|---|---|---|---|
| `OpenAICompatibleModelClient` | OpenAI `/responses` | SSE + JSON | `POST /v1/responses` | `supports_prompt_cache = True`（当 base_url 含 openai.com / right.codes） |
| `AnthropicCompatibleModelClient` | Anthropic `/messages` | JSON | `POST /v1/messages` | `supports_prompt_cache = False` |

两个 client 都实现了统一的 `complete(prompt, max_new_tokens, prompt_cache_key, prompt_cache_retention)` 接口。Runtime 层不感知底层协议差异。

**注意**：简历的"2 类"对应的是协议级别的分类。实际上支持的 provider 可以更多（DeepSeek、GPT、Claude 等都用这两个协议之一）。

---

## 2. "7 类工具" — (A) 代码静态数

**文件**: `iatcoder/tools/registry.py` 中的 `_TOOL_RUNNERS` 字典 + `BASE_TOOL_SPECS`

15 个注册工具函数按语义归为 7 类：

| 类别 | 包含工具 | 风险等级 |
|---|---|---|
| 文件浏览 | `list_files` | 只读 |
| 文件读取 | `read_file` | 只读 |
| 搜索 | `search` | 只读 |
| Shell | `run_shell` | 高风险 |
| 文件修改 | `write_file`, `patch_file` | 高风险 |
| TODO 管理 | `todo_add`, `todo_update`, `todo_list` | 只读 |
| 子 agent / plan / 交互 | `agent`, `send_message`, `task_stop`, `enter_plan_mode`, `exit_plan_mode`, `ask_user` | 混合 |

每个工具都有 `{schema, risky, description}` 三重定义，通过 `RegisteredTool` 注册进 harness。校验逻辑单独放在 `validate_tool()` 中做参数级检查。

---

## 3. "3 类运行工件" — (A) 代码静态数

**文件**: `iatcoder/core/run_store.py`

每次模型调用（一次 `ask()`）都会在 `.iatcoder/runs/<run_id>/` 下产生三类文件：

```
.iatcoder/runs/<run_id>/
├── task_state.json    # 任务状态快照（含 tool_steps, attempts, stop_reason, artifact_graph 等）
├── trace.jsonl        # 流式事件日志（逐行追加，含 prompt_built, tool_executed, checkpoint_created 等）
├── report.json        # 最终报告（含 prompt_metadata, resume_state, durable_promotions 等）
└── artifacts/         # 额外产物目录（长 shell 输出全文等）
```

**说明**：`artifacts/` 目录是补充产物，不算在"3 类"中。三类核心工件 `task_state.json`（可恢复）、`trace.jsonl`（可审计）、`report.json`（可复盘）是每次运行都产生的。

---

## 4. "12 组长上下文配置" — (B) 实验设计

**文件**: `iatcoder/evaluation/metrics.py` 函数 `run_real_context_experiment()` (line 897)

实验设计是 3 × 2 × 2 = **12 种配置**的笛卡尔积：

```
history_levels = [
    ("short",  4 轮历史),
    ("medium", 12 轮历史),
    ("long",   24 轮历史),
]
note_levels = [
    ("low",   2 条笔记),
    ("high",  10 条笔记),
]
request_levels = [
    ("short", "Reply with the target token only."),
    ("long",  "Reply with the target token only. Do not restate the prompt..."),
]
```

每种配置跑两个 variant：
- **`full`**：开启 `context_reduction`
- **`no_context_reduction`**：关闭 `context_reduction`

核心指标 (line 950)：

```python
"avg_prompt_compression_ratio": (avg_raw - avg_full) / avg_raw
```

---

## 5. "7082 → 5664，平均 16.19%，最高 33.28%" — (C) 实验结果

这组数字不是代码硬编码的，而是**运行 `run_real_context_experiment()` 的实际输出**。

计算逻辑在 `metrics.py:957-968`：

```python
"avg_prompt_compression_ratio": _safe_mean(ratios)       # → 16.19%
"max_prompt_compression_ratio": max(ratios)               # → 33.28%
"avg_full_prompt_chars": _safe_mean(full_chars)           # → 5664（开启裁剪）
"avg_raw_prompt_chars": _safe_mean(raw_chars)             # → 7082（关闭裁剪）
```

背后的裁剪机制在 `core/context_manager.py`：

```
6 个 Section:
  prefix (预算 12000, 地板 4000)
  memory (预算 8000, 地板 1200)
  skills (预算 4000, 地板 600)
  relevant_memory (预算 6000, 地板 1000)
  history (预算 30000, 地板 6000)
  current_request (永不裁剪)

裁剪顺序: relevant_memory → skills → history → memory → prefix
算法: 迭代式，每次只降一个 section 的预算，立即重新渲染检查是否达标。
```

---

## 6. "12 个记忆依赖任务" — (B) 实验设计

**文件**: `iatcoder/evaluation/metrics.py:331-344`

```python
MEMORY_EXPERIMENT_TASKS = [
    # 4 个 fact_lookup：读文件后 follow-up 确认事实
    {"id": "fact_color",   "category": "fact_lookup",       "filename": "facts.txt",   "fact": "deploy key is red"},
    {"id": "fact_api",     "category": "fact_lookup",       "filename": "settings.txt", "fact": "api base path is /v1/internal"},
    {"id": "fact_budget",  "category": "fact_lookup",       "filename": "limits.txt",   "fact": "default step budget is 6"},
    {"id": "fact_timeout", "category": "fact_lookup",       "filename": "runtime.txt",  "fact": "timeout ceiling is 120 seconds"},

    # 4 个 edit_dependency：读文件后依赖记忆编辑
    {"id": "edit_intro",   "category": "edit_dependency",    "filename": "README.md",   "fact": "first bullet is the locked intro line"},
    {"id": "edit_token",   "category": "edit_dependency",    "filename": "sample.txt",  "fact": "second token is placeholder"},
    {"id": "edit_field",   "category": "edit_dependency",    "filename": "config.txt",  "fact": "fixed field name is benchmark_schema"},
    {"id": "edit_line",    "category": "edit_dependency",    "filename": "notes.txt",   "fact": "locked marker is on line three"},

    # 4 个 history_reference：follow-up 问已建立的历史结论
    {"id": "history_file",  "category": "history_reference", "filename": "history.txt", "fact": "deploy fact came from facts.txt"},
    {"id": "history_line",  "category": "history_reference", "filename": "history.txt", "fact": "benchmark note came from line two"},
    {"id": "history_token", "category": "history_reference", "filename": "history.txt", "fact": "placeholder token was beta"},
    {"id": "history_tool",  "category": "history_reference", "filename": "history.txt", "fact": "inspection tool was read_file"},
]
```

实验流程 (line 382-401)：
1. **bootstrap**：agent 读文件记住事实
2. **follow-up**：关/开记忆系统，问 follow-up 问题
3. 记录 `followup_reads`——`_MemoryExperimentModelClient` 计数器中 follow-up 阶段每次 `read_file` 调用

---

## 7. "重复读文件 60 → 0" — (C) 实验结果

指标来自 `metrics.py:306,400`：

```python
"repeated_reads": int(getattr(agent.model_client, "followup_reads", 0))
```

12 个任务 × 5 次重复 = 60 次。在 `_run_memory_task_variant()` 中：
- **memory_on**：bootstrapped 阶段读过的文件，follow-up 时模型直接走记忆，不再调 `read_file` → **0 次**
- **memory_off**：关闭记忆系统，follow-up 时模型不知道已读过的内容 → 每次重复都要再次 `read_file`，累加到 **60 次**

---

## 8. "10 个恢复场景" — (B) 实验设计

**文件**: `iatcoder/evaluation/metrics.py:1269-1330`

```python
RECOVERY_ABLATION_TASKS = [
    # checkpoint 基础恢复
    {"id": "checkpoint_resume_goal",   "category": "checkpoint_resume"},
    {"id": "checkpoint_resume_files",  "category": "checkpoint_resume"},

    # 文件过期（stale）
    {"id": "partial_stale_single",     "category": "partial_stale"},       # 单文件过期
    {"id": "partial_stale_multi",      "category": "partial_stale"},       # 多文件过期

    # workspace 漂移
    {"id": "workspace_mismatch_fingerprint", "category": "workspace_mismatch"},  # 指纹不匹配
    {"id": "workspace_mismatch_runtime",     "category": "workspace_mismatch"},  # runtime identity 不匹配

    # schema 版本不匹配
    {"id": "schema_mismatch_version",  "category": "schema_mismatch"},     # 版本号不匹配
    {"id": "schema_mismatch_missing",  "category": "schema_mismatch"},     # 完全无 checkpoint

    # 部分成功恢复
    {"id": "partial_success_shell",    "category": "partial_success_recovery"},  # shell 部分失败
    {"id": "partial_success_tool",     "category": "partial_success_recovery"},  # 工具调用失败
]
```

每种用 `_RecoveryScenarioModelClient` 验证 prompt 中是否包含指定的 `required_fragments`。categories 在 `_recovery_variant_summary` 中聚合指标（line 1533-1542）。

---

## 9. "workspace 漂移识别率 100%，没有误信旧状态" — (C) 实验结果

检测逻辑在 `core/runtime.py:296-361` `evaluate_resume_state()`：

```
状态机:
  schema_version 不匹配 → schema_mismatch
  key_files 的 freshness 与实际不符 → partial-stale（并输出 stale_paths）
  runtime_identity 中 workspace_fingerprint / model / approval_policy 等改变 → workspace-mismatch
  一切正常 → full-valid
```

指标来自 `metrics.py:1541`：

```python
"workspace_drift_detection_rate": 正确报告的 workspace_mismatch / 总的 workspace_mismatch 场景
"resume_false_accept_rate": 不应该恢复却当成 full-valid 的比例
```

---

## 10. "固定回归任务 100% 通过/预算内/verifier 通过" — (C) 实验结果

**文件**: `benchmarks/coding_tasks.json` — 12 个固定任务：

| # | 任务 | 类别 |
|---|---|---|
| 1 | readme_intro_locked | documentation |
| 2 | readme_schema_note | documentation |
| 3 | sample_beta_locked | text-edit |
| 4 | sample_gamma_locked | text-edit |
| 5 | invalid_patch_recovery | tool-boundary |
| 6 | path_escape_recovery | tool-boundary |
| 7 | repeated_read_recovery | tool-boundary |
| 8 | context_reduction_checkpoint | recovery |
| 9 | freshness_reanchor_resume | recovery |
| 10 | workspace_mismatch_resume | recovery |
| 11 | durable_promotion_accept | durable-contract |
| 12 | durable_promotion_reject | durable-contract |

每个任务有 `step_budget`（预算上限）、`verifier`（Python 断言）、`fixture_repo`（固定 fixture）。通过 `ScriptedModelClient`（预定义输出）运行，验证 harness 自身机制是否正确，而非模型能力。

三个 100% 的含义：
- **pass_rate**：12 个任务全部 `status == "passed"`
- **within_budget_rate**：每个任务的 tool_steps ≤ step_budget
- **verifier_pass_rate**：每个任务的 verifier 断言全部通过

---

## 附录：简历遗漏的系统设计

以下是在代码中完整实现、但简历 6 条 bullet 没有覆盖的模块：

### 1. Plan Mode — `core/plan_mode.py`
读 → 计划 → 写 三段式工作流。plan 阶段只允许读工具 + 写 plan artifact，切换时自动换 tool profile + prefix。

### 2. Worker 子 Agent 系统 — `core/worker_manager.py` + `worker_runtime.py` + `worker_artifacts.py`
`agent` 工具可以 spawn Explore/Worker 子 agent，后台线程并行执行，父 agent 可 `send_message`/`task_stop` 控制。结果通过 `collect_worker_artifacts` 收集回主 session。

### 3. Sandbox Shell 隔离 — `features/sandbox/`
```text
features/sandbox/
├── __init__.py
├── config.py      # SandboxConfig（模式、backend）
├── runner.py      # SandboxRunner（执行隔离）
├── checker.py     # 命令安全检查
└── command_matcher.py  # 命令模式匹配
```
`run_shell` 可选走 sandbox backend，支持 `best_effort` 模式。

### 4. Skills 工作流系统 — `features/skills.py`
通过 `SKILL.md` 声明可复用工作流（/review, /test, /commit 等），支持 `$ARGUMENTS` 变量替换、frontmatter 元数据、自定义 prompt_fn。

### 5. Dream 后台记忆整合 — `features/memory.py`（line 500+）
把 daily log 中的笔记整合成 durable topic 文件。使用文件锁（`.consolidate-lock`）防并发，`HOLDER_STALE_S = 3600` 兜底 stale holder。

### 6. Prompt Cache 机制 — `core/context_manager.py` + `providers/clients.py`
对支持的 backend（OpenAI-compatible with right.codes/openai.com），算 prefix hash 作为 `prompt_cache_key`，设置 `prompt_cache_retention`。缓存命中和 miss 记录进 trace/report。

### 7. Tool Policy（fresh_read 前置检查）— `core/tool_policy.py`
`patch_file` 和 `write_file`（覆盖已有文件）前，强制要求先 `read_file` 拿到当前内容。用 `run_shell` 做搜索被拦截并提示改用 `search`/`read_file`。

### 8. Compact 历史压缩 — `core/compact.py`
与预算裁剪（budget reduction）不同，compaction 是合并早期轮次为一个 compact_summary，释放 history section 空间。支持 `files_read`、`files_modified`、`key_decisions`、`current_progress` 等结构化摘要字段。

### 9. Turn History 细粒度压缩 — `core/turn_history.py`
history 中的 3 种压缩手段：
- **Collapse duplicate reads**：同一文件在同一 turn 连续读 → 合为一行
- **File summary reuse**：如果文件有缓存的 file_summary，用摘要代替完整读取结果
- **Tool summarization**：旧 turn 的工具调用合并为摘要行

### 10. TUI 终端界面 — `iatcoder/tui/`
```text
iatcoder/tui/
├── __init__.py
├── app.py       # Textual App
├── main.py      # TUI 入口
└── widgets.py   # 自定义 widget
```
提供输入框、工具结果展示、状态栏、/slash command 补全等功能。
