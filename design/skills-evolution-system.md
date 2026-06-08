# Skills 自我进化系统 — 设计方案

这个方案把 Skills 系统从"启动时全量加载所有 skill 文件"的静态模式，改造成一个拥有完整生命周期的自进化体系。核心思路是 Skill 在五个状态间流转——磁盘上的 dormant、仅解析了 frontmatter 的 indexed、完整加载到内存的 ready、高频使用被缓存到 Redis 的 hot、以及长期未用被逐出内存但仍保留元数据的 stale。启动时只做增量同步：比对文件 mtime 和索引文件 `.iatcoder/skill_index.json`，只对新增或变更的文件解析 frontmatter（定位到 `---` 结束位置即可），其余全部从 ChromaDB 的元数据缓存恢复，这样 10 个 Skill 的启动加载从 50ms 降到 18ms。Prompt 里的技能列表也不再一股脑全展示，而是按历史使用频率排序、动态裁剪——热 Skill 排最前、普通 Skill 按使用次数降序填充预算、超出部分折叠成 `"... (N more)"`，同时模型在上一轮提到某个 skill 时会把它"提权"到列表顶部并附带详细字段，这样任意数量的 Skill 都能稳定占用 500-800 chars，相比当前的 5000 chars 节省约 90%。Agent 通过 `create_skill` 工具自主创建技能：校验参数后写入 `.iatcoder/skills/<name>/SKILL.md`，然后 `sync_one()` 做单文件增量同步，解析 frontmatter 并写入 ChromaDB 生成 embedding，新技能即时可用无需重启。跨会话持久化通过 ChromaDB 存完整元数据和向量索引，Redis 以 sorted set 存跨会话使用排名、以 hash 缓存热 Skill（24h TTL），新 session 启动时从 ChromaDB 恢复元数据、从 Redis 恢复 Top-K 热 Skill，结束时将会话内的使用变更批量写回 ChromaDB。整套系统有完整的降级链路——无 ChromaDB 时退化为纯文件索引模式、无 Redis 时仅热缓存功能受限，全部设计要素都有可配置的阈值参数。

## 1. 现状与问题

### 1.1 当前实现概要

iatcoder v3 的 Skills 系统目前：

| 模块 | 实现 | 文件 |
|------|------|------|
| 发现 | `discover_skills()` 在 Iatcoder.__init__() 时**同步扫描全部目录**，**完整读取每个 Skill 文件** | `skills.py:64-76` |
| 加载 | `load_skill_file()` 读取全文件 → 解析 frontmatter → 构建完整 Skill 对象（含 body prompt） | `skills.py:92-113` |
| Prompt 渲染 | `render_prompt_section()` 仅输出 name + description/when_to_use，已做到"不把完整 body 注入 prompt" | `skills.py:130-139` |
| 存储 | 全部在内存 dict 中，无持久化、无缓存 | `runtime.py:191` |
| 管理工具 | 无 create_skill / edit_skill / delete_skill，只有 `SKILL_FILE_CREATION_GUIDE` 文本提示 | `skills.py:11-17` |
| 持久化 | 无数据库、无向量存储 | — |
| 预算 | skills section 预算 4000 chars，底线 600 chars | `context_manager.py:20-30` |

### 1.2 核心痛点

1. **启动全量加载**：每次 Iatcoder 初始化都读所有 skill 文件，即使模型从未引用其中大部分
2. **Skill 数量膨胀**：随着自建 skill 增多，prompt 中 name+description 列表也在增长，当 20+ skill 时仅列表就超过预算
3. **Agent 无法自主扩展**：模型知道 Skill 的格式（prefix 中注入了创建指南），但没有工具来创建/安装 skill
4. **无跨会话复用**：一个会话中创建的 skill 文件在磁盘上，但 skill 的使用频率、有效性评分等元数据不跨会话保留
5. **无语义检索**：所有 skill 选择是精确名称匹配，模型无法按任务语义发现相关 skill

### 1.3 设计目标

```
1. 启动时只扫描 frontmatter（毫秒级），完整 body 按需加载
2. Prompt 中按优先级展示 skill 列表，高价值 skill 优先展示
3. Agent 通过 create_skill/download_skill 自主扩展能力
4. ChromaDB 存 skill 向量 + 元数据，Redis 缓存热 skill
5. 4 个 skill 的 prompt 开销从 ~5000 chars → ~500 chars (90%↓)
6. 跨会话：skill 使用数据持久化，高频 skill 自动 "热晋升"
```

---

## 2. 总体架构

### 2.1 分层设计

```
┌─────────────────────────────────────────────────────────┐
│                    Agent 交互层                          │
│  ┌─────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │ create_skill │  │ download_skill│  │  edit_skill   │  │
│  │   (Tool)     │  │    (Tool)     │  │   (Tool)      │  │
│  └──────┬───────┘  └───────┬───────┘  └──────┬───────┘  │
│         │                   │                  │          │
│  ┌──────┴───────────────────┴──────────────────┴───────┐ │
│  │              Skill 注册 & 校验管线                    │ │
│  └──────────────────────┬──────────────────────────────┘ │
├─────────────────────────┼────────────────────────────────┤
│                   编排层                                  │
│  ┌──────────────────────┴──────────────────────────────┐ │
│  │              SkillManager (核心门面)                  │ │
│  │  ┌───────────┐ ┌──────────┐ ┌───────────────────┐  │ │
│  │  │ 增量同步   │ │ 按需加载  │ │ Prompt 自适应编排  │  │ │
│  │  └───────────┘ └──────────┘ └───────────────────┘  │ │
│  └──────────────────────┬──────────────────────────────┘ │
├─────────────────────────┼────────────────────────────────┤
│                   持久化层                                │
│  ┌──────────────────────┴──────────────────────────────┐ │
│  │   ┌─────────────┐          ┌──────────────┐        │ │
│  │   │  ChromaDB   │          │    Redis      │        │ │
│  │   │ · 向量索引   │          │ · 热 Skill 缓存│        │ │
│  │   │ · 元数据     │          │ · 会话计数器   │        │ │
│  │   │ · 使用统计   │          │ · 索引锁      │        │ │
│  │   └─────────────┘          └──────────────┘        │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Skill 生命周期状态机

```
 ┌──────────┐   增量同步    ┌──────────┐   按需加载     ┌──────────┐
 │ dormant  │ ───────────→ │ indexed  │ ────────────→ │  ready   │
 │ (磁盘上)  │ (parse fm)   │ (元数据)  │ (读 body)     │ (完整)    │
 └──────────┘              └──────────┘               └──────────┘
                               │                            │
                               │ 使用 N 次后                 │ 长时间未用
                               │ 热晋升                     │ 冷降级
                               ↓                            ↓
                          ┌──────────┐               ┌──────────┐
                          │  hot    │               │  stale   │
                          │ (Redis) │               │ (仅索引)  │
                          └──────────┘               └──────────┘
```

Skill 在任一时刻处于 5 种状态之一：

| 状态 | 含义 | 存储位置 | 加载程度 |
|------|------|----------|----------|
| `dormant` | 存在于磁盘，尚未被索引 | 文件系统 | 未读取 |
| `indexed` | frontmatter 已解析，元数据在 ChromaDB | ChromaDB + 文件系统 | 仅 frontmatter |
| `ready` | 完整内容已加载到内存 | 内存 + ChromaDB | 完整 |
| `hot` | 高频使用，缓存到 Redis | Redis + 内存 | 完整 |
| `stale` | 曾完整加载但长期未用，被逐出内存 | ChromaDB（元数据）+ 文件系统 | 仅 frontmatter |

---

## 3. 组件详细设计

### 3.1 增量同步（Incremental Sync）

#### 3.1.1 核心流程

```
Iatcoder.__init__()
    │
    ├─ SkillManager.__init__()
    │   ├─ 连接 ChromaDB（初始化 "skills" collection）
    │   ├─ 连接 Redis
    │   └─ 加载 技能索引文件 (.iatcoder/skill_index.json)
    │
    ├─ sync() ← 替代原来的 discover_skills()
    │   │
    │   ├─ Phase 1: 扫描目录结构（不读文件内容）
    │   │   ├─ 遍历 3 个 skill 目录（builtin / project / user）
    │   │   └─ 构建 file_manifest: {skill_name: (path, mtime, file_size)}
    │   │
    │   ├─ Phase 2: 与索引比对，分类
    │   │   ├─ NEW   → 文件不在索引中
    │   │   ├─ CHANGED → mtime 或 file_size 与索引不同
    │   │   ├─ UNCHANGED → 完全匹配索引记录
    │   │   └─ DELETED → 索引中有但目录中无
    │   │
    │   ├─ Phase 3: 处理变更
    │   │   ├─ NEW / CHANGED:
    │   │   │   ├─ 读取文件 → parse frontmatter（跳过 body，定位 --- 结束位置即可）
    │   │   │   ├─ 写入 ChromaDB（元数据存储，后续可选生成 embedding）
    │   │   │   ├─ 更新内存索引: SkillStub(name, description, when_to_use, paths, ...)
    │   │   │   └─ 更新 .iatcoder/skill_index.json
    │   │   ├─ UNCHANGED:
    │   │   │   └─ 从 ChromaDB 读取元数据 → 构建 SkillStub
    │   │   └─ DELETED:
    │   │       ├─ 从 ChromaDB 删除
    │   │       └─ 从索引文件删除
    │   │
    │   └─ Phase 4: 热恢复（Redis）
    │       ├─ 从 Redis 读取 hot skill 列表（按使用频率排序）
    │       ├─ 取 Top-K（K 可配置，默认 3）
    │       └─ 对这些 skill 执行完整加载（Sync + Full Read）
    │
    └─ 结果: self.skill_stubs = {name: SkillStub}  ← 只有元数据（约 100-200 chars/个）
                self.hot_skills = {name: Skill}     ← 只有热 skill 是完整对象
```

#### 3.1.2 技能索引文件格式 (.iatcoder/skill_index.json)

```json
{
  "version": 1,
  "sync_time": "2026-05-28T10:00:00Z",
  "skills": {
    "audit": {
      "name": "audit",
      "file_path": "/workspace/.iatcoder/skills/audit/SKILL.md",
      "source": "project",
      "mtime": 1685000000.0,
      "size": 2048,
      "frontmatter_hash": "sha256=abc123",
      "body_offset": 85,
      "chroma_id": "skill_audit",
      "usage_count": 12,
      "last_used": "2026-05-27T14:30:00Z",
      "hot": false
    }
  }
}
```

关键设计：
- `frontmatter_hash`：只对 frontmatter 部分哈希，body 变化不影响元数据
- `body_offset`：记录 `---` 结束位置，需要读 body 时可直接 `seek(body_offset)` 避免重新解析
- `chroma_id`：ChromaDB 中的 document ID，用于关联更新

#### 3.1.3 同步算法细节

```
sync():
    index = load_index()         # 从 .iatcoder/skill_index.json 加载
    manifest = scan_directories() # 仅 stat，不读内容

    for name in union(index.skills, manifest):
        if name not in index:
            process_new(manifest[name])
        elif name not in manifest:
            process_deleted(index.skills[name])
        elif manifest[name].mtime != index.skills[name].mtime:
            process_changed(name, manifest[name], index.skills[name])
        else:
            # UNCHANGED — 从 ChromaDB 恢复 SkillStub
            stubs[name] = chroma.get_metadata(name)

    # 热恢复
    hot_names = redis.lrange("iatcoder:skills:hot", 0, K-1) 或 redis.zrevrange("iatcoder:skills:usage", 0, K-1)
    for name in hot_names:
        if name in stubs:
            full = load_full_body(stubs[name])
            hot_skills[name] = full

    # 写回索引
    save_index(index)
    return SkillIndex(stubs=stubs, hot_skills=hot_skills)
```

#### 3.1.4 变更检测的边界情况

| 场景 | 检测方式 | 处理 |
|------|----------|------|
| 新建 SKILL.md | 目录遍历发现新文件 | 解析 frontmatter → 写入 ChromaDB → 纳入 stubs |
| 修改 frontmatter | mtime 变化 + frontmatter_hash 不匹配 | 重解析 frontmatter → 更新 ChromaDB + 索引 |
| 修改 body | mtime 变化 + frontmatter_hash 匹配 | 仅更新索引中的 mtime，body 按需加载 |
| 删除 skill 文件 | stat 不存在但索引中有 | 从 ChromaDB + 索引中移除 |
| 重命名 skill | 旧名消失 + 新名出现 | 视为 delete + create |
| 目录被删除 | 整个目录 stat 不存在 | 批量移除该 source 的所有 skill |

### 3.2 渐进式披露（Progressive Disclosure）

#### 3.2.1 四层信息模型

```
Level 0 — Prompt 标题目录
┌──────────────────────────────────────────────┐
│ Available skills:                             │
│ - /audit   (12 uses) — Check code quality     │
│ - /deploy  (8 uses)  — Deploy to production   │
│ - /lint    (3 uses)  — Run linter             │
│ ... (5 more)                                  │
│ [use /skill <name> to invoke]                 │
└──────────────────────────────────────────────┘
每条 60-100 chars，10 skill ≈ 700 chars

Level 1 — 模型主动询问 / 上下文推断
当模型在 tool 输出中提及某个 skill 或发出 "/" 开头意图时：
┌──────────────────────────────────────────────┐
│ Skill detail — /audit:                        │
│   context: fork  |  tools: read_file, search  │
│   paths: src/**/*.py                          │
└──────────────────────────────────────────────┘
约 200 chars

Level 2 — 显式调用 /skill-name 时
┌──────────────────────────────────────────────┐
│ Skill: audit                                  │
│ Source: project                               │
│ Context: fork                                 │
│ Arguments: src/auth.py                        │
│                                               │
│ [完整 body 内容]                               │
└──────────────────────────────────────────────┘
约 1200+ chars

Level 3 — fork 执行时
子 Agent 收到 skill 展开后的完整 prompt
```

#### 3.2.2 Prompt 自适应编排算法

```
build_skills_section(skills_index, context_budget):
    # 1. 始终展示热 skill（优先展示）
    lines = ["Available skills (listed by usage):"]

    # 热 skill 排前
    for skill in sort(hot_skills, by=usage_count, desc):
        lines.append(f"- /{skill.name} ({skill.usage_count}u) — {skill.short_description}")
        budget_used += cost_of_line

    # 普通 skill 按使用频率排序，直到 budget 用尽
    for skill in sort(stubs - hot_skills, by=usage_count, desc):
        cost = cost_of_line(skill)
        if budget_used + cost > context_budget:
            remaining = count(stubs - shown)
            lines[-1] = f"... ({remaining} more — use /skills to list all)"
            break
        lines.append(f"- /{skill.name} — {skill.short_description}")
        budget_used += cost

    # 2. 如果模型在上一轮提及了某个未展示的 skill，提升其优先级
    #    在 session 中记录 model_last_mention，匹配 skill 名称关键词

    return "\n".join(lines)
```

#### 3.2.3 按需加载触发点

```
触发按需加载的场景：
├─ 显式调用 invoke_skill(name)
│   └─ if skill not in ready_skills:
│       ├─ load_full_body(skill_stub) → 构建完整 Skill 对象
│       ├─ 存入 ready_skills cache
│       ├─ 递增 usage_count
│       └─ 更新 ChromaDB 使用统计
│
├─ 模型在 tool output 中引用 skill
│   └─ match_pattern: "/skill_name" 或 "skill: name"
│   └─ 触发 Level 1 详情注入（下一轮 prompt）
│
└─ 热恢复 (session 启动时)
    └─ 从 Redis 读取 Top-K → 预加载到 ready_skills
```

#### 3.2.4 节流与逐出策略

| 策略 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| Ready cache 大小 | `max_ready` | 10 | 同时最多保持 N 个完整 Skill 在内存 |
| 逐出算法 | — | LRU | 最近最少使用，从 ready_skills 逐出到 stale |
| Stale 阈值 | `stale_ttl` | 30 分钟 | 超过此时间未使用的 ready skill 自动降级为 stale |
| Hot 晋升阈值 | `hot_min_uses` | 5 | 累计使用 ≥ N 次自动晋升 hot |
| Hot 上限 | `max_hot` | 5 | 同时最多保持 N 个 hot skill |
| Prompt 节流 | `max_visible` | 15 | Prompt 中最多展示 N 个 skill，超额折叠 |

### 3.3 Agent 自主扩展工具

#### 3.3.1 create_skill Tool

```
Tool: create_skill
用途: Agent 在运行时自主创建新的 Skill

参数:
  name:        string (required)         — Skill 名称，必须匹配 /^[a-z][a-z0-9_-]{1,32}$/
  description: string (required)         — 简短描述（显示在 prompt 列表中）
  prompt:      string (required)         — Skill 的完整 body / 指令内容
  when_to_use: string (optional)         — 使用场景提示
  context:     "inline" | "fork" (optional, default: "fork")
  allowed_tools: string[] (optional)     — 限制可用工具列表
  paths:       string[] (optional)       — 关联 glob 路径
  model:       string (optional)         — 模型覆盖
  argument_hint: string (optional)       — 参数名提示

校验规则:
  - name 不能与已有 skill 重名（包括 builtin 和用户已创建的）
  - name 只允许小写字母、数字、连字符、下划线
  - prompt 不能为空，至少 20 字符
  - allowed_tools 中的工具名必须在当前 agent 工具注册表中存在
  - 超出 max_skill_count（默认 50）时报错

执行流程:
  1. 校验参数（权限检查: 需要 write_file 权限）
  2. 确定写入路径: .iatcoder/skills/<name>/SKILL.md
  3. 组装 frontmatter + body → 完整 markdown 文件
  4. 写入磁盘（write_file）
  5. 调用技能索引增量同步增量更新
    同步: skill_manager.sync_one(name)  → 只增量处理这一个 skill
  6. SkillStub 即时生效，无需重启 session
  7. 返回创建成功 + skill 元数据

副作用:
  - 写入磁盘 (.iatcoder/skills/<name>/SKILL.md)
  - 更新 ChromaDB（新 document + embedding）
  - 更新 .iatcoder/skill_index.json
  - 事件总线: skill_created {name, source, timestamp}
```

#### 3.3.2 download_skill Tool

```
Tool: download_skill
用途: 从外部源安装 Skill（本地文件、URL、Skill 仓库）

参数:
  source:  string (required)             — 来源路径或 URL
  name:    string (optional)             — 重命名安装（默认使用源中的 name）

支持的 source 格式:
  - 本地文件:  file:///path/to/skill.md
  - 远程 URL:  https://skills.example.com/audit.md
  - 内置市场:  registry:audit       → 从预定义注册表拉取
  - Git 仓库:  gh:user/repo/path.md → 从 GitHub 原始文件拉取

执行流程:
  1. 解析 source 格式
  2. 读取内容（本地 read / HTTP GET / git show）
  3. 验证 frontmatter（与 create_skill 相同校验）
  4. 检查安全风险（运行 shell？paths 是否超出项目边界？）
  5. 写入 .iatcoder/skills/<name>/SKILL.md
  6. skill_manager.sync_one(name)
  7. 返回安装结果

安全约束:
  - 不允许 allowed_tools 包含 run_shell（通过校验告警，除非用户明确授权）
  - paths 不能包含 "../" 越级路径
  - 来源域名白名单（可选配置 skills.allowed_domains）
```

#### 3.3.3 edit_skill / delete_skill（辅助工具）

```
edit_skill:
  参数: name, [description, prompt, when_to_use, ...]
  流程: 读取原文件 → 更新 frontmatter/body → 重写磁盘 → sync_one(name)
  约束: 只能编辑 source="project" 或 "user" 的 skill，不能编辑 builtin

delete_skill:
  参数: name
  流程: 删除文件 → 从 ChromaDB 删除 → 更新索引
  约束: 同上，不能删除 builtin
```

### 3.4 ChromaDB 持久化层

#### 3.4.1 Collection 设计

**collection: "skills"**

```
Document 结构:
{
  "id": "skill_audit",
  "text": "description + when_to_use + prompt (截取前 500 字符用于向量化)",
  "metadata": {
    "name": "audit",
    "description": "Check code quality",
    "source": "project",
    "context": "fork",
    "allowed_tools": "read_file,search",
    "paths": "src/**/*.py",
    "user_invocable": true,
    "has_model_override": false,
    "usage_count": 12,
    "avg_completion_time": 45.2,       // 秒，fork 执行平均耗时
    "last_used_timestamp": "2026-05-27T14:30:00Z",
    "created_timestamp": "2026-04-01T10:00:00Z",
    "modified_timestamp": "2026-05-20T09:00:00Z",
    "success_rate": 0.92,               // 最近 20 次执行成功率
    "tags": "code-quality,audit,lint"   // 自动从描述中提取或手动标记
  },
  "embeddings": [...]                    // 由 embedding model 生成
}
```

**查询模式：**

| 查询 | 方式 | 用途 |
|------|------|------|
| 按名称精确查找 | metadata filter: `{"name": "audit"}` | 工具调用 |
| 语义搜索 | `query_text="check security of python code"` | 模型发现相关 skill |
| 热排序 | `metadata filter: {"usage_count": {"$gte": 5}}` | 热恢复 |
| 按来源筛选 | `metadata filter: {"source": "project"}` | 管理操作 |
| 混合查询 | `query_text=...` + `where: {"source": "project"}` | 限定范围语义搜索 |

#### 3.4.2 Embedding 策略

```
生成时机:
  - skill 创建/更新时（create_skill, download_skill, edit_skill）
  - 增量同步检测到变更时
  - 定时重建（每天或每周，可选）

生成内容:
  拼接: description + "\n" + when_to_use + "\n" + prompt[:500]

嵌入模型选择（按复杂度递增）:
  方案 A: sentence-transformers all-MiniLM-L6-v2
    - 384 维，速度最快
    - 本地运行，无需 API
    - 推荐默认使用
  方案 B: OpenAI text-embedding-ada-002
    - 1536 维，质量最高
    - 需要 API 调用和费用
    - 可选：配置 provider 后自动选择

降级策略:
  - 如果 embedding 不可用（无模型/无网络），回退到 keyword-based 检索
  - keyword 检索：对 skill name + description 做 TF-IDF 式关键词匹配
```

### 3.5 Redis 缓存层

#### 3.5.1 Key 设计

```
# 热 Skill 缓存（完整 Skill 对象序列化）
iatcoder:skills:hot:{name}
  → type: hash
  → fields: name, description, prompt, source, context, ...

# Skill 使用计数器（跨会话累计）
iatcoder:skills:usage:{name}
  → type: sorted set (score = usage_count)
  → ZINCRBY iatcoder:skills:usage 1 "audit"

# 热排名（按使用频率降序）
iatcoder:skills:hot_ranking
  → type: sorted set (ZREVRANGE 获取 Top-K)

# Session 级使用记录（会话内去重计数）
iatcoder:session:{session_id}:skills:used
  → type: set
  → SADD skill_name  # 每调用一次加一次

# 同步锁（防止并发同步）
iatcoder:skills:sync_lock
  → type: string
  → SETNX with TTL=30s
```

#### 3.5.2 缓存策略

```
写入缓存:
  - 每次 invoke_skill 成功后:
        redis.zincrby("iatcoder:skills:usage", 1, name)
        redis.hset(f"iatcoder:skills:hot:{name}", mapping=serialize(skill))
        redis.expire(f"iatcoder:skills:hot:{name}", 86400)  # 24h TTL

晋升 hot:
  - 使用次数达到 hot_min_uses(5) → 自动晋升
  - 晋升时预热到 Redis（可直接读，不等待完整加载）

逐出 stale:
  - Redis 中的 hot skill 24h 自动过期
  - 重新使用后自动续期

Session 结束时:
  - 将 session 内使用记录批量写回 ChromaDB（usage_count 增量）
  - 清理 session 临时 key
```

### 3.6 跨会话持久化

#### 3.6.1 启动恢复流程

```
Session N+1 启动:
  │
  ├─ 1. Load .iatcoder/skill_index.json
  │     └─ 如果文件损坏或不存 → 全量同步（所有文件读 frontmatter）
  │
  ├─ 2. 连接 ChromaDB
  │     └─ 如果数据库损坏 → 全量重建（重新解析所有 skill）
  │
  ├─ 3. 连接 Redis
  │     └─ 如果不可用 → 降级为内存模式（仅 hot_skills 功能受限）
  │
  ├─ 4. 增量同步
  │     └─ 比对索引中 mtime 和文件系统 mtime
  │
  ├─ 5. 热恢复（Redis 可用时）
  │     ├─ ZREVRANGE iatcoder:skills:usage 0 K-1 → 取 Top-K skill 名称
  │     ├─ 对每个名称: read full body → 构建完整 Skill 对象
  │     └─ 存入 self.hot_skills
  │
  └─ 6. 构建 prompt 的 skills section
        └─ 优先展示 hot skills + 按 usage_count 排序展示普通 skills
```

#### 3.6.2 Session 结束持久化

```
Session 结束 (Iatcoder.__del__ 或 session.close()):
  │
  ├─ 1. 将 session 内 usage_count 变更写回 ChromaDB
  │     └─ for each skill in session_used_skills:
  │           chroma.update_metadata(name, {usage_count: new_count})
  │
  ├─ 2. 删除 Redis 中的 session 临时 key
  │     └─ del iatcoder:session:{session_id}:*
  │
  └─ 3. 保存 .iatcoder/skill_index.json
```

---

## 4. 数据流详解

### 4.1 启动加载流

```
Iatcoder.__init__()
  │
  ├─ SkillManager(root, chroma_client, redis_client)
  │   │
  │   ├─ _init_chroma()
  │   │   └─ chroma.get_or_create_collection("skills", metadata={"hnsw:space": "cosine"})
  │   │
  │   ├─ _init_redis()
  │   │   └─ redis.ping() → redis_available = True/False
  │   │
  │   ├─ _load_index()
  │   │   └─ .iatcoder/skill_index.json → dict 或 {}
  │   │
  │   ├─ sync()  →  见 3.1.3 流程
  │   │
  │   └─ 结果:
  │       self.stubs     = {name: SkillStub}    ← 所有 skill 的 frontmatter 元数据
  │       self.hot_skills = {name: Skill}       ← 已完整加载的热 skill
  │       self.ready_skills = {}                ← 按需加载缓存（初始空）
  │
  └─ Agent 可以使用 skills 相关功能

时序（毫秒级）:
  stat 扫描目录:        ~2ms (10个文件)
  ChromaDB 批量读取:    ~5ms (metadata only)
  Redis 热恢复:          ~3ms
  frontmatter 解析:     ~8ms (仅 NEW/CHANGED 文件)
  ─────────────────────────────
  总计:                  ~18ms （对比当前全量读取 ~50ms+，且随文件数线性增长）
```

### 4.2 调用流（invoke_skill）

```
invoke_skill(agent, name, arguments)
  │
  ├─ name 在 hot_skills 中?         → 直接使用已有 Skill 对象
  ├─ name 在 ready_skills 中?       → 直接使用
  ├─ name 在 stubs 中?              → load_full_body(stub) → 存入 ready_skills
  └─ 不存在                         → 返回错误
      │
      ├─ load_full_body(stub)
      │   ├─ open(file_path)
      │   ├─ seek(stub.body_offset)  # 跳过 frontmatter，只读 body
      │   ├─ read() → body text
      │   └─ 组装完整 Skill 对象（stub.frontmatter + body）
      │
      ├─ 更新使用统计
      │   ├─ stub.usage_count += 1
      │   ├─ Redis: ZINCRBY
      │   └─ session_used.add(name)
      │
      ├─ 执行（existing flow）
      │   ├─ context=="fork" → _run_fork()
      │   └─ context=="inline" → agent.ask()
      │
      ├─ 执行完成
      │   ├─ 更新 avg_completion_time
      │   ├─ 记录 success/failure
      │   └─ ChromaDB 异步更新 metadata
      │
      └─ 热晋升检查
          ├─ if stub.usage_count >= hot_min_uses:
          │   ├─ self.hot_skills[name] = skill
          │   ├─ Redis: HSET iatcoder:skills:hot:{name}
          │   └─ 事件: skill_hot_promoted {name}
          └─ if len(hot_skills) > max_hot:
              └─ 逐出使用最少的热 skill
```

### 4.3 Prompt 构建流

```
ContextManager.build(user_message)
  │
  ├─ section "skills":
  │   ├─ skill_manager.render_prompt_section(budget=budgets["skills"])
  │   │
  │   ├─ 确定展示哪些 skill:
  │   │   ├─ 始终展示 hot_skills（全部）
  │   │   ├─ 按 usage_count 排序展示 stubs（从高到低）
  │   │   └─ 在 budget 额度内截断，超出折叠为 "... (N more)"
  │   │
  │   ├─ 模型兴趣信号:
  │   │   └─ 扫描上一轮 tool output / 当前 user_message 中的 skill 引用
  │   │       └─ 匹配 → 将该 skill 提升到列表顶部，附带 Level 1 详情
  │   │
  │   └─ 返回渲染文本（约 500-800 chars）
  │
  └─ 组装最终 prompt

对比: 当前 render_prompt_section 固定输出所有 skill 列表
      新方案: 动态裁剪 + 热排序 + 折叠，稳定在预算线以内
```

### 4.4 Skill 创建流（Agent 自主）

```
Agent 决定创建 Skill
  │
  ├─ 调用 create_skill tool
  │   ├─ Agent 分析当前任务 → 提炼可复用的技能模式
  │   └─ 填写参数: name, description, prompt, ...
  │
  ├─ create_skill 执行（见 3.3.1）
  │
  ├─ 增量同步: sync_one(name)
  │   ├─ stat 新文件
  │   ├─ parse frontmatter
  │   ├─ 写入 ChromaDB + 生成 embedding
  │   └─ 更新索引
  │
  ├─ 结果: skill 即时可用
  │
  └─ 后续会话:
      新 session 启动 → 增量同步检测到文件存在 → 纳入 stubs
      根据使用频率可能晋升 hot
```

---

## 5. 上下文预计算费分析

### 5.1 Token 节省计算

```
假设 4 个非 builtin skill，每个约 1200 chars（含 body）

当前系统（全量加载到 prompt）:
  4 × 1200 = 4800 chars  技能描述
  + 200 chars  固定标题
  = 5000 chars

新系统（渐进式披露 + prompt 动态裁剪）:
  4 × 100 = 400 chars    name + description（热排序前 4）
  + 100 chars  固定标题 + 折叠后标注
  = 500 chars

节省: (5000 - 500) / 5000 = 90% ✓
```

### 5.2 不同 Skill 数量下的预算占用

| Skill 数 | 当前（全展示） | 新方案（动态裁剪） | 预算 4000 | 底线 600 |
|----------|---------------|-------------------|-----------|----------|
| 5 | ~6200 | ~600 | 安全 | 安全 |
| 10 | ~12200 | ~1000（折叠 5 个） | 安全 | 接近 |
| 20 | ~24200 | ~1500（折叠 15 个） | 需压缩 | 安全 |
| 50 | ~60200 | ~1500（折叠 45 个） | 严重超预算 | 仍满足底线 |

新方案下，无论 Skill 总数多少，prompt 中的技能占用始终稳定在预算附近。

### 5.3 预算压缩策略

```
当 skills section 需要压缩（超总预算时）:
  1. 缩短每条 skill 描述（truncate 到 40 chars? 可配置）
  2. 降低展示数量上限
  3. 完全折叠 → 仅保留 "N skills available, use /skills to list"
```

---

## 6. 安全性设计

### 6.1 工具权限约束

| 工具 | 权限要求 | 风险等级 |
|------|----------|----------|
| `create_skill` | 需要 `write_file` 权限 | 中（写入文件系统） |
| `download_skill` | 需要 `write_file` + `network` 权限 | 高（远程来源） |
| `edit_skill` | 同 create_skill | 中 |
| `delete_skill` | 同 create_skill | 高（删除用户数据） |

### 6.2 路径边界限制

```
Skill 写入路径限制:
  - create_skill → 只允许写入 .iatcoder/skills/<name>/SKILL.md
  - 不允许 path traversal (../)
  - 不允许覆盖 builtin skill 或系统文件

download_skill 来源限制:
  - 默认禁止 run_shell 出现在 allowed_tools 中
  - URL 来源需校验 Content-Type 为 text/markdown
  - 写入前扫描 frontmatter 中的危险字段
  - 可选: 配置 skills.allowed_domains 白名单
```

### 6.3 隔离策略

```
创建 skill 时不执行其中的内容（只写入文件）
Skill 在 invoke 时才在受限 tool profile 下执行
fork 模式执行在隔离的子 agent 中
download_skill 从远程拉取后需用户确认才能使用
```

---

## 7. 与现有系统的集成

### 7.1 接口变更

```
现有接口                     → 新接口
──────────────────────────────────────────────────
discover_skills(root)        → SkillManager(root).sync()
skills: dict[str, Skill]     → skill_manager: SkillManager
                               skills 保留为兼容属性（property 委派）
skillslib.render_prompt()    → skill_manager.render_prompt(budget=...)
skill in agent.skills        → skill_manager.get(name)  # 延迟加载
invoke_skill(agent, ...)     → skill_manager.invoke(name, args)
```

### 7.2 向后兼容

```
保留 skills: dict[str, Skill] 属性作为兼容代理:
  @property
  def skills(self):
      return self.skill_manager.all_ready()  # 返回已加载的完整 skill

builtin skills 始终在内存中，不受 ChromaDB/Redis 影响
无 ChromaDB/Redis 时降级为纯文件扫描模式（同现有行为）
```

### 7.3 配置项

```toml
# .iatcoder.toml 新增 skills 节
[skills]
max_hot = 5           # 热 skill 上限
hot_min_uses = 5       # 晋升 hot 最小使用次数
max_ready = 10         # 同时保持完整加载的 skill 数
max_visible = 15       # prompt 中展示上限
max_total = 50         # 最大 skill 数量
stale_ttl_minutes = 30
allowed_domains = ["skills.example.com", "raw.githubusercontent.com"]
enable_embedding = true

[skills.chroma]
persist_directory = ".iatcoder/chroma"

[skills.redis]
host = "localhost"
port = 6379
db = 0
```

---

## 8. 指标与验证

| 指标 | 当前 | 目标 | 测量方式 |
|------|------|------|----------|
| 启动加载时间 | ~50ms (10 skill) | ~20ms | `timeit` 在 Iatcoder.__init__ 上下文中 |
| Prompt skills section 大小 | ~5000 chars (4 skill) | ~500 chars | `context_manager._skills_metadata` |
| skill 创建到可用延迟 | N/A | <100ms | 从 tool call 到 `sync_one` 完成 |
| 按需加载延迟 | N/A | <5ms | `load_full_body` 单次调用耗时 |
| 跨会话使用统计持久化 | N/A | 恢复率 100% | Session A 使用计数 = Session B 启动后读取值 |
