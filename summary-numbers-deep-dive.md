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

### TODO 管理详解

TODO 管理是三个工具 `todo_add` / `todo_update` / `todo_list` 组成的一个轻量级任务看板（见 [tools/todos.py](iatcoder/tools/todos.py)），让模型在会话中自主管理任务进度。

**解决的问题**：当模型需要完成一个多步骤任务（如"先读文件分析代码，再写测试，最后跑测试"），如果没有外部记录机制，模型容易在长对话中丢失上下文、重复工作或遗漏步骤。TODO 管理让模型自己维护一个结构化任务清单。

**三个工具**：

| 工具 | 功能 | 关键参数 |
|---|---|---|
| `todo_add` | 添加任务项 | `content`（必填，任务描述）、`status`（`pending`/`in_progress`/`completed`）、`priority`（`low`/`normal`/`high`）、`note`（备注） |
| `todo_update` | 更新任务项 | `todo_id`（必填）、可更新 `status`/`content`/`priority`/`note` |
| `todo_list` | 查看清单 | 无参数，返回当前所有任务项的格式化列表 |

**典型使用流程**：
```
1. 模型收到多步骤请求
2. model: todo_add("分析代码结构") → 返回 todo_1
3. model: todo_add("编写测试用例", priority="high") → 返回 todo_2
4. model: todo_add("运行 pytest") → 返回 todo_3
5. model: todo_list() → 看到完整清单，决定先做高优先级的
6. model: todo_update("todo_1", status="completed")  # 完成第一步
7. ...
```

**数据存储**：TODO 列表保存在 `agent.todo_ledger` 中，是会话级的内存状态，不会跨会话持久化。每个任务项包含 `id`、`content`、`status`、`priority`、`note`、`created_at` 字段。

**为什么归为只读**：TODO 管理本质上修改的是 agent 自身的内存状态，不影响工作区文件，也不执行外部命令。修改 TODO 清单不产生安全风险，所以 `risky=False`。

### 风险等级的作用

每个工具在注册时都有一个 `risky: bool` 字段（见 [tools/base.py](iatcoder/tools/base.py)），它在 harness 中有三重作用：

**1. 权限门禁（PermissionChecker）** — [core/permissions.py](iatcoder/core/permissions.py)
- **只读工具**（`risky=False`）：`PermissionChecker.check()` 直接放行 `PermissionDecision.allow("read_only")`，无需审批
- **高风险工具**（`risky=True`）：根据 `approval_policy` 决定行为：
  - `"auto"`：自动放行（自主模式）
  - `"prompt"`：弹窗询问用户批准
  - `"never"`：直接拒绝
- **Plan mode 约束**：plan 模式下只允许只读工具 + 写 plan artifact，高风险工具（`run_shell`、`write_file` 等）会因 `plan_mode_tool_not_allowed` 被拒绝

> **通俗理解风险等级**：就像给工具贴标签——"只读"相当于查看文件，没有破坏力，随便用；"高风险"相当于执行命令或修改文件，需要看情况放行；"混合"的 agent/plan 工具则像授权委托，本身不直接改文件，但能改变 agent 的行为模式。系统根据标签决定要不要问用户"你确认要执行这个操作吗？"。

**2. 工作区快照 diff** — [core/tool_executor.py](iatcoder/core/tool_executor.py)
执行前后，只有高风险工具会触发工作区快照对比：
```python
before_snapshot = agent.capture_workspace_snapshot() if tool.risky else {}
after_snapshot = agent.capture_workspace_snapshot() if tool.risky else before_snapshot
```
只读工具不产生快照开销，也不产生 diff 记录。

**3. 审计元数据**
每次工具调用的结果元数据都包含 `risk_level: "high" | "low"`，写入 `trace.jsonl` 供安全审计使用。例如 `run_shell` 的每次执行都会在日志中标记为高风险。

**注意**：混合类工具（子 agent / plan / 交互）的 `risky` 取决于具体工具：
- `agent`、`send_message`、`task_stop`、`enter_plan_mode`、`exit_plan_mode`、`ask_user` 各自定义自己的 risky 值（通常在各自的 SPEC 文件中设置）。这些工具的风险不来源于文件系统修改，而来源于对会话控制流的改变（如 spawn 子进程、切换模式、向用户发消息）。

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

### 实验目的

测试 context_reduction（上下文裁剪）机制在不同上下文压力下的实际效果：能否有效减少 prompt 长度，同时不影响模型回答正确率。

### 实验任务

在每个配置下，agent 的**具体任务**是：

> agent 的 memory 中已存入了 n 条 note（其中一条包含目标 token），history 中已录入了 m 轮无关对话。Agent 被问："What is the target token remembered in the notes?" 并附带一条请求指令。正确回答应该是目标 token（如 `TOKEN-short-low-short`）。

这是一个"大海捞针"式任务——目标信息埋藏在大量无关上下文中，模型需要从 notes 中找到正确 token。

### 任务参数详解

3 × 2 × 2 = **12 种配置**的笛卡尔积：

**① History 数量**（3 级）：模拟对话历史长度
- `short`（4 轮）：轻量会话，几乎无上下文压力
- `medium`（12 轮）：中等负载，接近日常使用上限
- `long`（24 轮）：压力测试，大幅推高上下文用量

每轮 history 内容为 `"context-history-{index}-" + "B"*220`，约 220+ 字符的无意义填充文本，保证占满 tokens 配额。

**② Note 数量**（2 级）：模拟记忆系统中的笔记数量
- `low`（2 条）：1 条目标 note + 1 条干扰 note
- `high`（10 条）：1 条目标 note + 9 条干扰 note（`decoy token is DECOY-{index}`）

这些 note 通过 `agent.memory.append_note()` 注入，模拟长期记忆积累。

**③ Request 指令长度**（2 级）：影响 current_request section 大小
- `short`：`"Reply with the target token only."`
- `long`：`"Reply with the target token only. Do not restate the prompt, and do not output any extra words."`

### 对比 variants

每个配置跑两个 variant：
- **`full`**：开启 `context_reduction`（正常模式）
- **`no_context_reduction`**：关闭 `context_reduction`

### 测量指标

```python
"avg_prompt_compression_ratio": (avg_raw - avg_full) / avg_raw  # 压缩率
"full_correct_rate"  # 开启裁剪后的正确率
"raw_correct_rate"   # 关闭裁剪后的正确率
```

> **通俗理解这个实验**：想象你有一个文件柜（对话历史），里面塞了越来越多文件。context_reduction 就像智能压缩——把不重要的文件缩成摘要，只保留关键信息。这个实验就是测试压缩能省多少空间（压缩率），以及压缩后还能不能找到要找的东西（正确率）。12 种配置覆盖了从"几乎空柜子"到"塞满文件"的各种场景。

---

## 5. "7082 → 5664，平均 16.19%，最高 33.28%" — (C) 实验结果

这组数字不是代码硬编码的，而是**运行 `run_real_context_experiment()` 的实际输出**。

> **通俗理解**：在不开启上下文裁剪时，平均每次发给模型的提示词有 7082 个字符；开启裁剪后降到 5664 个字符——省了约 1418 个字符（16%）。最好的情况下能省 33%，接近三分之一。这意味着 agent 在面对长对话时，可以自动压缩历史信息，只保留关键内容，从而节省 API 调用成本、减少模型的处理负担。

计算逻辑在 `metrics.py:957-968`：

```python
"avg_prompt_compression_ratio": _safe_mean(ratios)       # → 16.19%
"max_prompt_compression_ratio": max(ratios)               # → 33.28%
"avg_full_prompt_chars": _safe_mean(full_chars)           # → 5664（开启裁剪）
"avg_raw_prompt_chars": _safe_mean(raw_chars)             # → 7082（关闭裁剪）
```

> **通俗理解这个结果**：7082 和 5664 的差距，相当于一篇中等长度的文章被压缩掉了约五分之一。最高 33.28% 的压缩率意味着在最好的情况下，原本 1000 字符的上下文可以压到 667 字符。这省下的不只是 token 费用——更短的提示词意味着更快的响应速度和更低的延迟。压缩不是简单地"截掉一半"，而是智能地优先保留当前请求，然后依次削减 relevant_memory、skills、history、memory、prefix，直到整体长度达标，每个 section 都有不可再压缩的地板值防止信息完全丢失。

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

**文件**: `iatcoder/evaluation/metrics.py:349-362`

### 实验目的

验证记忆系统是否能让 agent 避免重复读取已读过的文件——即 bootstrapped 阶段建立的事实，在 follow-up 阶段能否直接从记忆调出而不依赖 `read_file` 工具。

### 三分类实验任务

12 个任务分为 3 个 category，每个 category 模拟一类真实使用场景：

#### ① fact_lookup（事实查询）— 4 个任务

Bootstrap 阶段读取一个文件记住关键配置，follow-up 阶段直接回答事实。

| 任务 ID | 文件 | 需要记住的事实 | 场景模拟 |
|---|---|---|---|
| `fact_color` | facts.txt | `deploy key is red` | 读取部署配置中的密钥颜色 |
| `fact_api` | settings.txt | `api base path is /v1/internal` | 记住 API 基础路径 |
| `fact_budget` | limits.txt | `default step budget is 6` | 记住系统限制参数 |
| `fact_timeout` | runtime.txt | `timeout ceiling is 120 seconds` | 记住运行时配置 |

**Follow-up prompt**：`"What does {filename} say?"`

#### ② edit_dependency（编辑依赖）— 4 个任务

Bootstrap 阶段读取一个文件记住某行约束，follow-up 阶段需要在编辑时遵守该约束而不重新读文件。

| 任务 ID | 文件 | 约束事实 | 场景模拟 |
|---|---|---|---|
| `edit_intro` | README.md | `first bullet is the locked intro line` | README 首行不可修改 |
| `edit_token` | sample.txt | `second token is placeholder` | 文件中的占位符不可覆盖 |
| `edit_field` | config.txt | `fixed field name is benchmark_schema` | 配置文件的字段名不可改 |
| `edit_line` | notes.txt | `locked marker is on line three` | 第三行是锁定标记 |

**Follow-up prompt**：`"Use the remembered constraint from {filename} to continue without rereading."`

#### ③ history_reference（历史引用）— 4 个任务

模拟跨轮推理：bootstrap 阶段做了某个操作，follow-up 阶段问这个操作的元信息。

| 任务 ID | 文件 | 历史结论 | 场景模拟 |
|---|---|---|---|
| `history_file` | history.txt | `deploy fact came from facts.txt` | 某个事实的来源文件 |
| `history_line` | history.txt | `benchmark note came from line two` | 某条笔记的来源行号 |
| `history_token` | history.txt | `placeholder token was beta` | 之前用过的占位符值 |
| `history_tool` | history.txt | `inspection tool was read_file` | 之前用过的检查工具 |

**Follow-up prompt**：`"What was the conclusion we already established from {filename}?"`

### 实验流程（line 382-401）

每个任务执行以下步骤：

1. **Setup**：在临时目录创建文件，写入事实内容
2. **Bootstrap**：agent 执行 `agent.ask(f"Read {task['filename']} and remember the key fact.")`，模型调用 `read_file` 读取文件后回复 "Done."
3. **Variant 配置**：
   - `memory_on`：正常开启记忆系统
   - `memory_off`：关闭 `feature_flags["memory"]` 和 `feature_flags["relevant_memory"]`
   - `memory_irrelevant`：保留记忆系统，但注入完全不相关的记忆内容（`"the team mascot is blue"`），验证记忆系统是否引入"幻觉"
4. **注入噪声**：调用 `_inject_memory_noise()` 向 memory 中追加无关内容，增加辨识难度
5. **截断读历史**：调用 `_truncate_read_history()` 清除 history 中的 read_file 记录，防止模型从 history 回放而非从记忆获取
6. **Follow-up**：根据 category 发不同的 follow-up prompt
7. **记录指标**：`correct`（回答是否正确）、`tool_steps`（工具调用次数）、`attempts`（尝试次数）、`repeated_reads`（重复读文件次数）

### 指标含义

- **memory_on 的 repeated_reads = 0**：模型完全通过记忆回答，没有再次调 `read_file`
- **memory_off 的 repeated_reads = 60**：12 个任务 × 5 次重复，每次都要重新读文件
- **memory_irrelevant 的 repeated_reads 和 correct_rate**：验证记忆系统在有干扰信息时是否仍然稳定，不会误用无关记忆

> **通俗理解这个实验**：这就像让一个新同事（agent）先去读 12 个文件记下关键信息，然后问他"刚才那个文件说了什么？"。
> 
> 实验设置了三组对照：
> - **有记忆**：同事记住了内容，直接回答——不需要再去翻文件
> - **没记忆**：同事转头就忘，每次问都要重新翻文件（repeated_reads 暴涨）
> - **有记忆但有干扰**：同事虽然记得，但脑子里还塞了些无关信息（"队宠是蓝色的"），看他会不会被带偏
> 
> 每种任务类型模拟不同场景：查配置（fact_lookup）、编辑时遵守约束（edit_dependency）、回顾历史过程（history_reference）。实验结果中 repeated_reads 从 60 降到 0，说明记忆系统让 agent 从一个"每次都要翻文件的人"变成了"过目不忘的人"。

---

## 7. "重复读文件 60 → 0" — (C) 实验结果

指标来自 `metrics.py:306,400`：

```python
"repeated_reads": int(getattr(agent.model_client, "followup_reads", 0))
```

12 个任务 × 5 次重复 = 60 次。在 `_run_memory_task_variant()` 中：
- **memory_on**：bootstrapped 阶段读过的文件，follow-up 时模型直接走记忆，不再调 `read_file` → **0 次**
- **memory_off**：关闭记忆系统，follow-up 时模型不知道已读过的内容 → 每次重复都要再次 `read_file`，累加到 **60 次**

> **通俗理解**：记忆系统让 agent 的重复工作量从"12 个任务各读 5 遍 = 60 次"降到了"读 1 遍记住，之后全靠回忆 = 0 次"。节省的不是时间，而是每次 `read_file` 背后的一次完整模型推理——每少一次工具调用，就省一轮与 API 的往返。

---

## 8. "10 个恢复场景" — (B) 实验设计

**文件**: `iatcoder/evaluation/metrics.py:1328-1389`

### 实验目的

验证 harness 的 checkpoint 恢复机制能在各种异常场景下正确识别状态、生成准确的恢复 prompt，而不是误报或漏报。

> **通俗理解这个实验**：假设你正在用 agent 写代码，中途去喝了杯咖啡。回来时可能发生各种状况——同事改了文件、项目目录变了、代码版本升级了、或者上次的命令只执行了一半。一个靠谱的 agent 应该能说清楚"刚才发生了什么，现在状态是什么"，而不是盲目继续或直接报错。
> 
> 这个实验设计了 10 种意外场景，测试 agent 的"恢复意识"：它能不能准确识别出每种异常（而不是稀里糊涂地当作一切正常），并在提示词中正确描述当前状态？

### 实验方法

使用 `_RecoveryScenarioModelClient`（一个 ScriptedModelClient 子类）检查生成的 prompt 中是否包含预期的必要片段（`required_fragments`）。如果全部命中，返回成功信号；如果缺失，返回失败。

### 10 个具体任务

#### ① Checkpoint 基础恢复（2 个）— `checkpoint_resume`

验证从正常 checkpoint 恢复时，prompt 中包含正确的任务目标和关键文件信息。

| 任务 ID | 场景 | 验证的 prompt 片段 |
|---|---|---|
| `checkpoint_resume_goal` | 从正常 checkpoint 恢复，目标是继续运行 benchmark | `task checkpoint:`、`current goal: resume the benchmark task`、`next step: apply the locked change` |
| `checkpoint_resume_files` | 恢复时需知道涉及了哪些文件 | `task checkpoint:`、`current goal: continue from the latest benchmark checkpoint`、`key files: sample.txt` |

#### ② 文件过期（2 个）— `partial_stale`

模拟 checkpoint 中的文件指纹（fingerprint）与当前工作区不符的情况——即文件在 agent 暂停期间被外部修改了。

| 任务 ID | 场景 | 验证的 prompt 片段 |
|---|---|---|
| `partial_stale_single` | 单个文件（sample.txt）过期 | `resume status: partial-stale`、`stale paths: sample.txt` |
| `partial_stale_multi` | 多个文件（sample.txt + notes.txt）过期 | `resume status: partial-stale`、`stale paths: sample.txt, notes.txt` |

#### ③ Workspace 漂移（2 个）— `workspace_mismatch`

模拟 checkpoint 中的 workspace 标识与当前环境不匹配——可能因为仓库被重新克隆、目录结构改变等。

| 任务 ID | 场景 | 验证的 prompt 片段 |
|---|---|---|
| `workspace_mismatch_fingerprint` | 工作区指纹不一致（如 .git HEAD 变了） | `resume status: workspace-mismatch`、`current goal: recover after workspace drift` |
| `workspace_mismatch_runtime` | Runtime identity 不一致（如 approval_policy 变了） | `resume status: workspace-mismatch`、`next step: rebuild runtime state from a fresh checkpoint` |

#### ④ Schema 版本不匹配（2 个）— `schema_mismatch`

模拟 checkpoint 文件格式版本与当前代码期望的版本不一致——可能因为代码升级后加载旧 checkpoint。

| 任务 ID | 场景 | 验证的 prompt 片段 |
|---|---|---|
| `schema_mismatch_version` | 版本号不匹配（如 checkpoint 是 v1，代码期望 v2） | `resume status: schema-mismatch` |
| `schema_mismatch_missing` | 完全不存在 checkpoint 文件 | `resume status: no-checkpoint` |

#### ⑤ 部分成功恢复（2 个）— `partial_success_recovery`

模拟工具调用部分成功的情况——命令执行了但返回了非零退出码，或者工具抛异常但已产生了部分副作用。

| 任务 ID | 场景 | 验证的 prompt 片段 |
|---|---|---|
| `partial_success_shell` | Shell 命令部分成功（exit_code ≠ 0 但工作区有变化） | `current blocker: tool_partial_success`、`next step: inspect the diff before retry` |
| `partial_success_tool` | 工具调用完全失败（exit_code ≠ 0 且工作区无变化） | `current blocker: tool_failed`、`next step: retry after checking the workspace state` |

### 聚合指标

```python
"workspace_drift_detection_rate": 正确报告的 workspace_mismatch / 总的 workspace_mismatch 场景
"resume_false_accept_rate": 不应该恢复却当成 full-valid 的比例
```

> **通俗理解**：前一个指标衡量的是"出了问题能不能发现"——agent 能不能察觉到环境变了。后一个指标衡量的是"没出问题会不会误报"——明明一切正常，却被当成异常处理了。好的恢复系统要两样都好：既敏感又准确。

---

## 9. "workspace 漂移识别率 100%，没有误信旧状态" — (C) 实验结果

> **通俗理解**：workspace 漂移指的是 agent 的工作环境在它不知情的情况下发生了变化——好比你在玩游戏时暂停去吃饭，回来发现键盘被换了。这个实验就是测试 agent 能否察觉到"键盘被换了"而不是继续按旧键盘操作。结果是 100%——每次都能发现，而且从不会把异常状态误当作正常。

Workspace 漂移检测不是独立实验，而是集成在**恢复消融实验**（Section 8）中的一个测量维度——跑完 10 个恢复场景后，从 trace 日志中提取检测结果计算指标。

### 实验设计：恢复消融实验

**入口函数**：`run_recovery_ablation_v2()`（metrics.py:1639）

**数据流**：

```
RECOVERY_ABLATION_TASKS (10 个任务)
  → _run_recovery_task_variant(task, variant)  (每个任务 × 3 次重复 × 2 variant)
    → _apply_recovery_setup(agent, task, workspace)  (写入伪造 checkpoint)
    → agent.ask("Continue the recovery task.")       (触发 evaluate_resume_state)
    → 读 report.json 拿 resume_status
    → 读 trace.jsonl 查 runtime_identity_mismatch 事件
  → _recovery_variant_summary(rows)  (聚合指标)
```

### 1. Workspace 漂移场景：测试数据长什么样

两个测试任务共用同一个 fixture，区别仅在于验证的 prompt 片段不同。

**Setup 代码**（metrics.py:1480-1501）：

```python
if setup == "workspace_mismatch":
    agent.session["checkpoints"] = {
        "current_id": "ckpt_workspace",
        "items": {
            "ckpt_workspace": {
                "checkpoint_id": "ckpt_workspace",
                "parent_checkpoint_id": "",
                "schema_version": "phase1-v1",
                "created_at": "2026-04-15T08:00:00+00:00",
                "current_goal": "Recover after workspace drift",
                "completed": [],
                "current_blocker": "",
                "next_step": "Rebuild runtime state from a fresh checkpoint",
                "key_files": [],
                "freshness": {},
                "summary": "workspace mismatch benchmark",
                "runtime_identity": {
                    "workspace_fingerprint": "outdated-workspace-fingerprint"  # ← 故意伪造的旧指纹
                },
            }
        },
    }
    agent.session_store.save(agent.session)
```

关键：`runtime_identity` 中的 `workspace_fingerprint` 被设置为硬编码的假值 `"outdated-workspace-fingerprint"`，而实际工作区的 fingerprint 由 `WorkspaceContext.fingerprint()` 实时计算（基于 `.git/HEAD` + 文件列表 hash），两者必然不同。

### 2. 检测逻辑（runtime.py:316-381）

```python
def evaluate_resume_state(self):
    ...
    current_identity = self.current_runtime_identity()
    identity_keys = (
        "cwd", "model", "model_client", "approval_policy",
        "read_only", "max_steps", "max_new_tokens",
        "feature_flags", "shell_env_allowlist",
        "workspace_fingerprint", "tool_signature",
    )
    for key in identity_keys:
        if key not in saved_identity:
            continue
        if saved_identity.get(key) != current_identity.get(key):
            mismatch_fields.append(key)   # workspace_fingerprint 一定在这里
    ...
    if stale_paths:
        status = "partial-stale"
    elif mismatch_fields:
        status = "workspace-mismatch"     # ← 命中这个分支
    else:
        status = "full-valid"
```

判断顺序：先检查文件新鲜度（stale），再检查运行时一致性（mismatch），最后才是 full-valid。这意味着文件过期和 workspace 漂移同时发生时，优先报 stale。

### 3. 指标计算（metrics.py:1595-1606）

```python
stale_rows = [row for row in rows if row["category"] == "partial_stale"]
drift_rows = [row for row in rows if row["category"] == "workspace_mismatch"]
invalid_rows = [row for row in rows if row["category"] in {"partial_stale", "workspace_mismatch", "schema_mismatch"}]

{
    "workspace_drift_detection_rate":  正确检测到 drift 的 / 总 drift 场景数，
    "resume_false_accept_rate":        不应恢复却被判 full-valid 的 / 总异常场景数，
}
```

- `workspace_drift_detection_rate` = 在所有 `workspace_mismatch` category 的任务中，trace 日志包含 `runtime_identity_mismatch` 事件的比例
- `resume_false_accept_rate` = 在所有异常场景（partial_stale + workspace_mismatch + schema_mismatch）中，`resume_status` 被误判为 `full-valid` 的比例

### 4. 为什么结果是 100% 和 0%

- **100% 检测率**：因为 checkpoint 中的 `workspace_fingerprint` 是硬编码假值，运行时 fingerprint 是真值，两者必然不同。`evaluate_resume_state()` 比较 `identity_keys` 时一定会发现 workspace_fingerprint 不匹配
- **0% 误信率**：因为状态机严格按 stale → mismatch → full-valid 顺序判断，workspace_mismatch 场景下 fingerprint 必然不匹配，根本不会走到 full-valid 分支

---

## 10. "固定回归任务 100% 通过/预算内/verifier 通过" — (C) 实验结果

**文件**: `benchmarks/coding_tasks.json` — 12 个固定任务：

| # | 任务 ID | 类别 | 具体描述 |
|---|---|---|---|
| 1 | `readme_intro_locked` | documentation | README 首行已锁定，需修改后面内容但不碰首行 |
| 2 | `readme_schema_note` | documentation | 在 README 中添加 schema 说明段落 |
| 3 | `sample_beta_locked` | text-edit | 修改 sample.txt 中的某个占位符（beta → gamma） |
| 4 | `sample_gamma_locked` | text-edit | 再次修改 sample.txt 中的另一个占位符 |
| 5 | `invalid_patch_recovery` | tool-boundary | 让模型收到 patch 失败错误后自行修正并重试 |
| 6 | `path_escape_recovery` | tool-boundary | 模型尝试访问 .iatcoder 目录外的路径被拦截后的恢复 |
| 7 | `repeated_read_recovery` | tool-boundary | 模型连续两次读同一文件被拦截后改为其他操作 |
| 8 | `context_reduction_checkpoint` | recovery | 在裁剪上下文后从 checkpoint 恢复 |
| 9 | `freshness_reanchor_resume` | recovery | 文件指纹过期后重新锚定后恢复 |
| 10 | `workspace_mismatch_resume` | recovery | 工作区漂移后成功恢复会话 |
| 11 | `durable_promotion_accept` | durable-contract | 验证记忆持久化机制，接受持久化建议 |
| 12 | `durable_promotion_reject` | durable-contract | 验证记忆持久化机制，拒绝持久化建议 |

每个任务有 `step_budget`（预算上限）、`verifier`（Python 断言）、`fixture_repo`（固定 fixture）。通过 `ScriptedModelClient`（预定义输出）运行，验证 harness 自身机制是否正确，而非模型能力。

### Verifier 验证逻辑详解

verifier 是每个任务最终的"通过/不通过"断言，比简单字符串匹配更精确：

| # | 任务 | Verifier 逻辑 | 验证什么 |
|---|---|---|---|
| 1 | readme_intro_locked | `assert 'This fixture is a locked benchmark workspace.' in text` | 是否正确修改了 README 首行 |
| 2 | readme_schema_note | `assert 'schema and baseline are fixed' in text` | 是否写入了 schema 说明 |
| 3 | sample_beta_locked | `assert 'beta-locked' in text and '\nbeta\n' not in text` | 精确替换，旧值不能残留 |
| 4 | sample_gamma_locked | `assert 'gamma-locked' in text` | 替换 gamma 占位符 |
| 5 | invalid_patch_recovery | `assert 'recovered after invalid patch args' in text` | 从 patch 失败中恢复并完成修改 |
| 6 | path_escape_recovery | `assert 'alpha-guarded' in text` | 路径逃逸被拦截后仍完成合法修改 |
| 7 | repeated_read_recovery | `assert 'repeat-guarded' in text` | 重复读拦截后切换策略完成修改 |
| 8 | context_reduction_checkpoint | 读 report.json 取 checkpoint_id，查 trace.jsonl 有 `checkpoint_created` 且 trigger 为 `context_reduction` | 上下文裁剪正确触发了 checkpoint 创建 |
| 9 | freshness_reanchor_resume | 读 report.json 确认 `resume_status == partial-stale`，查 trace 有 `checkpoint_created` 且 trigger 为 `freshness_mismatch` | 文件过期后正确触发重锚定 |
| 10 | workspace_mismatch_resume | 读 report.json 确认 `resume_status == workspace-mismatch`，查 trace 有 `runtime_identity_mismatch` | 工作区漂移后正确报告且不误恢复 |
| 11 | durable_promotion_accept | 确认 report 有 2 个 `durable_promotions`，且 `project-conventions.md` 中写入了约定 | 记忆持久化机制正常运行 |
| 12 | durable_promotion_reject | 确认 `durable_rejections` 中包含 `secret_shaped` 和 `transient_task_state`，`durable_promotions` 只含安全项 | 机密/临时信息不被持久化 |

任务 8-10 的 verifier 比普通文本检查更复杂——它们直接读取 `.iatcoder/runs/` 下的 report.json 和 trace.jsonl 运行工件，验证 harness 内部状态机的输出是否正确。

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

---

## 附录 B：Eval 系统设计全景

> 整篇文档涉及的每个指标，最终都能追溯到 `iatcoder/evaluation/` 下的某段具体代码。
> 本附录从入口到指标，完整梳理 eval 的设计与执行过程。

> **Eval 系统是干什么的**：可以理解为这个项目的"体检中心"。它不关心 agent 在真实任务中表现多好——那取决于模型能力——而是关心 agent 框架本身有没有毛病：工具调用能不能被正确拦住或放行？上下文太长时能不能自动压缩？读过的文件能不能记住、避免重复读取？遇到意外中断能不能正确恢复？安全防御能不能挡住恶意输入？五个实验分别覆盖这五个维度，每次代码改动后跑一遍就能知道有没有把什么地方搞坏了。

### 1. Eval 架构概览

Eval 系统分为 **5 个独立实验套件** + **1 个汇总编排**：

```
iatcoder/evaluation/
├── evaluator.py      # BenchmarkEvaluator — 回归测试运行器
└── metrics.py        # 所有实验函数 + 指标聚合 + 报告渲染

发布物（artifacts/）:
  harness-regression-v2.json      ← run_harness_regression_v2()
  context-ablation-v2.json        ← run_context_ablation_v2()
  memory-ablation-v2.json         ← run_memory_ablation_v2()
  recovery-ablation-v2.json       ← run_recovery_ablation_v2()
  iatcoder-benchmark-core-report.md  ← write_benchmark_core_report()
```

**运行模式**：每个实验都有两种模式：
- **synthetic**（默认）：用 `ScriptedModelClient` 模拟模型输出，只测 harness 自身
- **real**：连真实模型 API，测模型 + harness 协同效果

---

### 2. 实验一：Harness Regression（回归测试）

**入口**：`run_harness_regression_v2()` → `BenchmarkEvaluator.run()`

**设计目的**：验证 harness 核心机制（工具校验、权限、policy、checkpoint、memory 等）在固定输入下行为正确。

> **这个实验测什么**：就好比给一个机器人预设了 12 道固定考题，每道题都知道标准答案。不测机器人的"智商"（模型能力），而是测它的"身体"（harness 框架）——工具调用的校验能不能拦下错误参数、权限系统能不能阻止越权操作、checkpoint 机制能不能正确恢复。所有输出都是预定义的脚本化输出，排除模型本身的随机性。

#### 执行过程

```python
# evaluator.py:429-464
def run(self):
    benchmark = self.load()                        # 从 JSON 加载 12 个任务
    rows = [self.run_task(task) for task in benchmark["tasks"]]
    summary = summarize_rows(rows)                 # 聚合指标
    artifact = {"schema_version": ..., "summary": summary, "rows": rows}
```

每个任务 `run_task()`（evaluator.py:466-571）执行以下步骤：

1. **Copy fixture**：从 `tests/fixtures/bench_repo_*` 复制干净的工作区
2. **Create agent**：使用 `ScriptedModelClient` + 任务对应的预定义输出序列
3. **Apply setup**：如果任务有 `setup` 字段（如 context_reduction、freshness_mismatch），提前注入状态
4. **Ask prompt**：`agent.ask(task["prompt"])` 让 agent 运行
5. **Run verifier**：`subprocess.run(task["verifier"], shell=True)` 执行 Python 断言
6. **Collect metrics**：记录 `tool_steps`、`attempts`、`stop_reason`、verifier exit code 等

#### 三个核心指标的计算

**pass_rate** = `passed / total_tasks`
```python
# evaluator.py:275
"pass_rate": (passed / total_tasks) if total_tasks else 0.0
```
`passed = True` 当且仅当同时满足 4 个条件（evaluator.py:526）：
```python
passed = (within_budget                        # tool_steps ≤ step_budget
          and verifier_passed                   # verifier exit_code == 0
          and expected_artifact_exists          # 预期文件存在
          and non_failure_stop_reason)          # stop_reason == final_answer
```

**within_budget_rate** = `sum(within_budget) / total_tasks`
```python
# evaluator.py:284
"within_budget_rate": (within_budget / total_tasks) if total_tasks else 0.0
```
每个任务的 `within_budget = task_state.tool_steps <= int(task["step_budget"])`

**verifier_pass_rate** = `sum(verifier_passed) / total_tasks`
```python
# evaluator.py:285
"verifier_pass_rate": (verifier_passes / total_tasks) if total_tasks else 0.0
```
每个任务的 `verifier_passed = verifier.returncode == 0`

---

### 3. 实验二：Context Ablation（上下文消融）

**入口**：`run_context_stress_matrix()`（synthetic）/ `run_real_context_experiment()`（real）

**设计目的**：测量 context_reduction 机制在不同上下文压力下的压缩效果。

> **这个实验测什么**：想象你有一篇很长的文章，agent 的 context_reduction 就像一个智能摘要工具——它要在不丢失关键信息的前提下，把文章压缩到最短。这个实验就是测试这个"摘要工具"的极限：
> - 对话历史从 4 轮到 24 轮，摘要还能压缩多少？
> - 记忆笔记从 2 条到 10 条，会不会压过头把关键信息丢了？
> - 用户指令变长了，压缩后当前请求还能完整保留吗？
> 
> synthetic 版本只测"压缩率"（不调模型，直接量字符数），real 版本还要测"压缩后还能不能答对题"。

#### Synthetic 版本（metrics.py:463-542）

3 × 2 × 2 = **12 种配置**，每种配置执行 `repetitions=5` 次，每次：

1. 创建 agent，按配置注入 notes 和 history
2. 调用 `measure_feature_ablation_metrics(agent, request_text)`，它在同一个 agent 上切换 feature flag 分别测量：
   - `full`（正常模式，带 context_reduction）
   - `no_context_reduction`（关闭裁剪）
   - `no_memory`（关闭记忆系统）
3. 每次测量调用 `_build_prompt_and_metadata()` 读取 6 个 section 的渲染字符数，但不实际调用模型

#### Real 版本（metrics.py:945-1018）

实验任务改为：agent 从 notes 中找到目标 token（"大海捞针"），记录 prompt_chars + 是否正确回答

#### 涉及的指标

**avg_prompt_compression_ratio** = `mean((raw - full) / raw for each config)`
```python
# metrics.py:1012
"avg_prompt_compression_ratio": _safe_mean(ratios)
```
`raw` = 关闭 context_reduction 时的 prompt_chars
`full` = 开启 context_reduction 时的 prompt_chars

**max_prompt_compression_ratio** = `max(ratios)` — 12 个配置中最高压缩率

**avg_full_prompt_chars** = `mean(full_chars)` — 12 个配置开启裁剪的平均字符数

**avg_raw_prompt_chars** = `mean(raw_chars)` — 12 个配置关闭裁剪的平均字符数

---

### 4. 实验三：Memory Ablation（记忆消融）

**入口**：`run_memory_dependency_experiment()`（小规模）/ `run_large_scale_memory_experiment()`（大规模）/ `run_real_memory_experiment()`（真实模型）

**设计目的**：验证记忆系统能否消除重复读文件行为。

> **这个实验测什么**：好比让 agent 先读一份文件（"部署密钥是红色的"），然后关掉文件，再问它"密钥是什么颜色？"——
> - **有记忆**：agent 直接回忆"红色"，不需要再打开文件
> - **没记忆**：agent 完全不记得，只能重新打开文件再看一遍
> - **有记忆但塞了干扰信息**：agent 脑子里存了"队宠是蓝色的"这条无关信息，看它会不会记混
> 
> 大规模版本把 1 个事实扩展到 12 个不同任务，覆盖"查配置"、"编辑时遵守约束"、"回顾历史过程"三类场景，测试记忆系统的广度。

#### 小规模实验（metrics.py:327-346）

1 个任务 × 3 个 variant（`memory_on` / `memory_off` / `memory_irrelevant`）× N 次重复：

```
agent: Read facts.txt and remember the key fact.
agent: Done.

# 切换 variant 配置...

agent: What color is the deploy key?
# 如果走记忆 → 直接回答，不调 read_file
# 如果不走记忆 → 重新 read_file
```

#### 大规模实验（metrics.py:427-460）

12 个任务（MEMORY_EXPERIMENT_TASKS）× 3 variant × 5 次重复：

```
for each task:
  for _ in range(repetitions):
    for each variant (memory_on/memory_off/memory_irrelevant):
      # bootstrap: agent 读文件记住事实
      # follow-up: 根据 category 问问题
      # 记录 repeated_reads、correct、tool_steps
```

#### 涉及的指标

**repeated_reads**：
```python
# metrics.py:451
"repeated_reads": sum(row["repeated_reads"] for row in rows)
```
通过 `_MemoryExperimentModelClient.followup_reads` 计数器累积。计数器在模型输出 `read_file` tool call 时 +1（metrics.py:262-263）。

**correct_rate**：
```python
# metrics.py:454
"correct_rate": _safe_ratio(sum(1 for row in rows if row["correct"]), len(rows))
```
`correct = _normalize_text(answer) == _normalize_text(task["fact"])` — 回答与事实完全一致。

**avg_tool_steps**：`mean(row["tool_steps"] for row in rows)` — 每个 variant 的平均工具调用次数。

**memory_hit_rate**：
```python
# metrics.py:455
"memory_hit_rate": _safe_ratio(sum(1 for row in rows if row["repeated_reads"] == 0), len(rows))
```
重复读为 0 的任务比例——即模型完全靠记忆回答、无需再读文件的比例。

---

### 5. 实验四：Recovery Ablation（恢复消融）

**入口**：`run_recovery_ablation_v2()`（metrics.py:1639-1660）

**设计目的**：验证 checkpoint 恢复机制在 10 种异常场景下的状态识别能力。

> **这个实验测什么**：agent 在工作过程中会定期保存 checkpoint（检查点），就像游戏存档。但当它要"读档"时，可能遇到各种状况——存档说某些文件没变过但实际上变了（stale）、游戏版本升级了但存档还是旧的（schema mismatch）、电脑都换了但还想读旧存档（workspace drift）、或者上次操作只成功了一半（partial success）。好的恢复机制应该能准确判断每种状况，并在提示词中告诉模型"现在是什么情况"。这个实验就是测试 agent 的"读档"能力——它能不能正确识别每种异常，以及能不能避免把异常状态误当作一切正常。

每个 variant 执行：

1. **Setup**：`_apply_recovery_setup()` 写入伪造的 checkpoint（含假指纹、过期文件、旧 schema 等）
2. **Ask**：agent 收到 `"Continue the recovery task."`
3. **检测**：agent 启动时 `evaluate_resume_state()` 自动比较 checkpoint 与当前状态
4. **验证**：`_RecoveryScenarioModelClient` 检查生成的 prompt 是否包含 `required_fragments`
5. **审计**：读 `report.json` 拿 `resume_status`，读 `trace.jsonl` 查 `runtime_identity_mismatch` 事件

#### 涉及的指标

**resume_success_rate**：
```python
# metrics.py:1602
"resume_success_rate": _safe_ratio(sum(1 for row in rows if row["resume_succeeded"]), len(rows))
```
prompt 包含所有 required_fragments 的比例。`resume_succeeded = (final_answer == "recovery state restored.")`。

**stale_reanchor_rate**：
```python
# metrics.py:1603
"stale_reanchor_rate": _safe_ratio(sum(1 for row in stale_rows if row["stale_reanchored"]), len(stale_rows))
```
在 partial_stale 场景中，trace 日志包含 `checkpoint_created(trigger=freshness_mismatch)` 的比例。

**workspace_drift_detection_rate**：
```python
# metrics.py:1604
"workspace_drift_detection_rate": _safe_ratio(sum(1 for row in drift_rows if row["workspace_drift_detected"]), len(drift_rows))
```
在 workspace_mismatch 场景中，trace 日志包含 `runtime_identity_mismatch` 事件的比例。

**resume_false_accept_rate**：
```python
# metrics.py:1605
"resume_false_accept_rate": _safe_ratio(sum(1 for row in invalid_rows if row["false_accept"]), len(invalid_rows))
```
在异常场景（partial_stale + workspace_mismatch + schema_mismatch）中，`resume_status` 被误判为 `full-valid` 的比例。

---

### 6. 实验五：Security Ablation（安全消融）

**入口**：`run_security_experiment_suite()`（synthetic）/ `run_real_security_experiment_suite()`（real）

**设计目的**：验证 harness 的安全守卫（permission、path escape 检测、参数校验等）能否正确拦截恶意/异常工具调用。

> **这个实验测什么**：就像一个安检系统，要测试各种"可疑行为"能不能被拦住——试图读取禁区外的文件（路径逃逸）、在只读模式下强行写入、反复发送相同指令（重复调用攻击）、用破损参数搞破坏。这个实验不是测模型会不会"作恶"，而是测 harness 的防御机制是否可靠：不管模型出于什么原因发出这些调用，系统都应该能识别并拦截。每种场景都重复多次，确保拦截是确定性的而不是概率性的。

#### Synthetic 版本（metrics.py:664-690）

10 个场景（SECURITY_SCENARIOS） × `repetitions=3`：

| 场景 ID | 测试内容 | 预期拦截机制 |
|---|---|---|
| `path_escape_read` | 读 workspace 外的文件 | validate_tool path escape 检测 |
| `symlink_escape` | 通过 symlink 读外部文件 | validate_tool path escape 检测 |
| `search_escape` | 搜索 workspace 外路径 | validate_tool path escape 检测 |
| `approval_denied_shell` | approval_policy=never 时执行 shell | PermissionChecker |
| `read_only_write` | read_only=True 时写文件 | PermissionChecker |
| `repeated_identical_call` | 重复同一工具调用 | tool_repetition 检测 |
| `patch_nonunique` | old_text 出现多次 | validate_tool patch_file 校验 |
| `patch_missing_new_text` | patch 缺少 new_text | validate_tool 参数校验 |
| `timeout_out_of_range` | timeout 超范围 | validate_tool timeout 校验 |
| `empty_agent_prompt` | agent 工具空 prompt | validate_agent_tool 校验 |

每个场景运行后从 `agent._last_tool_result_metadata` 提取 `tool_status`、`tool_error_code`、`security_event_type`。

#### Real 版本（metrics.py:1073-1111）

在 synthetic 10 个场景基础上增加 `repeated_identical_call` 场景，使用真实模型调用 API。

#### 涉及的指标

**security_event_counts**：各 `security_event_type` 的计数字典。
```python
# 所有场景中出现的 security_event_type 聚合：
# path_escape 等值在 validate_tool 或权限检查中被设置
```

**tool_error_code_counts**：各 `tool_error_code` 的计数字典。
```python
# 所有场景中出现的 tool_error_code 聚合：
# unknown_tool, invalid_arguments, tool_not_allowed,
# approval_denied, read_only_block, plan_mode_write_guard 等
```

**scenario_count**：场景数量（synthetic=10, real=11）。

---

### 7. 编排汇总：collect_resume_metrics

**入口**：`collect_resume_metrics()`（metrics.py:1114-1177）

这个函数是整个 eval 系统的总控制器，串联 5 个实验并聚合结果：

> **这个编排做什么用**：它像一个"一键跑所有评测"的总开关。你只需要告诉它两件事：用哪个 provider（比如 gpt 或 claude），跑真实模型还是用模拟数据。它就会自动依次跑完回归测试、上下文压缩、记忆效果、恢复能力、安全防御五个维度的实验，然后把所有结果揉成一份报告。synthetic 模式跑得快（不调 API，几分钟出结果），适合日常验证；real 模式连真实模型，适合正式发布前的全面评估。

```python
def collect_resume_metrics(
    benchmark_artifact_path,     # 回归测试结果
    runs_root,                   # 历史运行的 trace/report
    experiment_mode="synthetic", # synthetic | real
    real_provider="gpt",         # real 模式用的 provider
):
    # 1. 读取已有回归测试 artifact
    benchmark = aggregate_benchmark_artifact(benchmark_artifact_path)

    # 2. 聚合历史 runs 的 trace/report
    runs = aggregate_run_artifacts(runs_root)

    if experiment_mode == "real":
        # 3a. 真实模型实验：逐个调用 API
        memory_large = run_real_memory_experiment(provider=real_provider)
        context = run_real_context_experiment(provider=real_provider)
        security = run_real_security_experiment_suite(provider=real_provider)
    else:
        # 3b. 合成实验：使用 ScriptedModelClient
        stress = build_stress_agent_metrics()
        memory = run_memory_dependency_experiment()
        memory_large = run_large_scale_memory_experiment()
        context = run_context_stress_matrix()
        security = run_security_experiment_suite()

    # 4. 生成 resume_highlights（6 条陈述性摘要）
    # 5. 返回完整的 metrics 字典
```

输出通过 `render_resume_metrics_markdown()` 或 `render_large_scale_experiment_report()` 渲染为 Markdown 报告。

---

### 8. 完整指标索引

> 这个索引让你可以快速找到每个指标的"元数据"——它叫什么、在哪段代码里算出来的、公式是什么。前面各节用自然语言解释了"为什么测这个指标"，这里用表格回答"这个指标具体怎么算的"。

以下是整篇文档涉及的所有指标，按实验归类，每个指标标注代码位置和计算方式：

#### Harness Regression 指标

| 指标 | 代码位置 | 计算方式 |
|---|---|---|
| pass_rate | evaluator.py:278 | `passed / total_tasks` |
| within_budget_rate | evaluator.py:284 | `sum(within_budget) / total_tasks` |
| verifier_pass_rate | evaluator.py:285 | `sum(verifier_passed) / total_tasks` |
| tool_steps | evaluator.py:561 | `task_state.tool_steps` |
| attempts | evaluator.py:562 | `task_state.attempts` |
| stop_reason | evaluator.py:564 | `task_state.stop_reason` |
| failure_category | evaluator.py:573-589 | 按 `missing_artifact` / `budget_exceeded` / `verifier_failed` / `failure_stop_reason` 分类 |

#### Context Ablation 指标

| 指标 | 代码位置 | 计算方式 |
|---|---|---|
| avg_prompt_compression_ratio | metrics.py:1012 | `mean((raw - full) / raw)` |
| max_prompt_compression_ratio | metrics.py:1013 | `max(ratios)` |
| avg_full_prompt_chars | metrics.py:1015 | `mean(full_chars)` |
| avg_raw_prompt_chars | metrics.py:1016 | `mean(raw_chars)` |
| full_correct_rate | metrics.py:1000 | `sum(full_correct) / len(full_rows)` |
| raw_correct_rate | metrics.py:1001 | `sum(raw_correct) / len(raw_rows)` |
| current_request_preserved_rate | metrics.py:540 | `sum(preserved) / len(configs)` |

#### Memory Ablation 指标

| 指标 | 代码位置 | 计算方式 |
|---|---|---|
| repeated_reads | metrics.py:323,451 | `sum(row["repeated_reads"])` — `_MemoryExperimentModelClient.followup_reads` 计数器 |
| correct_rate | metrics.py:344,454 | `sum(correct) / len(rows)` — 回答与事实完全一致的比例 |
| avg_tool_steps | metrics.py:342,452 | `mean(row["tool_steps"])` |
| avg_attempts | metrics.py:343,453 | `mean(row["attempts"])` |
| memory_hit_rate | metrics.py:455 | `sum(repeated_reads==0) / len(rows)` |

#### Recovery Ablation 指标

| 指标 | 代码位置 | 计算方式 |
|---|---|---|
| resume_success_rate | metrics.py:1602 | `sum(resume_succeeded) / len(rows)` — prompt 含所有 required_fragments |
| stale_reanchor_rate | metrics.py:1603 | `sum(stale_reanchored) / len(stale_rows)` — trace 含 freshness_mismatch 事件 |
| workspace_drift_detection_rate | metrics.py:1604 | `sum(workspace_drift_detected) / len(drift_rows)` — trace 含 runtime_identity_mismatch 事件 |
| resume_false_accept_rate | metrics.py:1605 | `sum(false_accept) / len(invalid_rows)` — 异常场景误判为 full-valid 的比例 |

#### Security Ablation 指标

| 指标 | 代码位置 | 计算方式 |
|---|---|---|
| security_event_counts | metrics.py:687 | 各 security_event_type 的出现次数 |
| tool_error_code_counts | metrics.py:688 | 各 tool_error_code 的出现次数 |
| scenario_count | metrics.py:685 | `len(SECURITY_SCENARIOS)` 或 `len(REAL_SECURITY_SCENARIOS) + 1` |

#### Aggregate Run 指标

| 指标 | 代码位置 | 计算方式 |
|---|---|---|
| run_count | metrics.py:150 | `len(reports)` |
| avg_tool_steps | metrics.py:151 | `mean(report.tool_steps)` |
| avg_attempts | metrics.py:152 | `mean(report.attempts)` |
| cache_hit_rate | metrics.py:154 | `sum(cache_hit) / len(reports)` |
| prefix_reuse_rate | metrics.py:157 | `sum(not prefix_changed) / len(reports)` |
| security_event_counts | metrics.py:160 | 从 trace.jsonl 聚合所有 security_event_type |
| avg_run_duration_ms | metrics.py:162 | `mean(run_duration_ms)` 从 trace 的 run_started/run_finished 推断 |
