"""会话级任务看板（Todo Ledger）。

模型可通过 todo_add/todo_update/todo_list 工具管理任务状态，
用于多步规划中跟踪进度。"""

from .workspace import now

VALID_STATUS = {"pending", "in_progress", "done", "blocked"}
VALID_PRIORITY = {"low", "normal", "high"}


class TodoLedger:
    def __init__(self, runtime):
        """初始化 TodoLedger，绑定 runtime 实例。"""
        self.runtime = runtime
        self.runtime.session.setdefault("todos", {"next_id": 1, "items": []})

    @property
    def state(self):
        """获取或初始化 todo 存储字典。"""
        return self.runtime.session.setdefault("todos", {"next_id": 1, "items": []})

    def add(self, content, status="pending", priority="normal", note=""):
        """添加一条新 todo 项。"""
        status = _clean_status(status)
        priority = _clean_priority(priority)
        todo_id = f"todo_{int(self.state.get('next_id', 1))}"
        self.state["next_id"] = int(self.state.get("next_id", 1)) + 1
        item = {
            "id": todo_id,
            "content": str(content).strip(),
            "status": status,
            "priority": priority,
            "note": str(note or "").strip(),
            "created_at": now(),
            "updated_at": now(),
        }
        self.state.setdefault("items", []).append(item)
        self._record_change("add", item)
        return item

    def update(self, todo_id, **changes):
        """更新已存在 todo 项的字段。"""
        item = self.get(todo_id)
        for key in ("content", "note"):
            if key in changes and changes[key] is not None:
                item[key] = str(changes[key]).strip()
        if changes.get("status") is not None:
            item["status"] = _clean_status(changes["status"])
        if changes.get("priority") is not None:
            item["priority"] = _clean_priority(changes["priority"])
        item["updated_at"] = now()
        self._record_change("update", item)
        return item

    def get(self, todo_id):
        """根据 todo_id 查找 todo 项。"""
        for item in self.state.setdefault("items", []):
            if item.get("id") == str(todo_id):
                return item
        raise ValueError(f"unknown todo_id: {todo_id}")

    def render_list(self):
        """将 todo 列表渲染为可读文本。"""
        items = list(self.state.setdefault("items", []))
        if not items:
            return "Task ledger:\n- empty"
        lines = ["Task ledger:"]
        for item in items:
            note = f" ({item['note']})" if item.get("note") else ""
            lines.append(f"- {item['id']} [{item['status']}] {item['priority']} - {item['content']}{note}")
        return "\n".join(lines)

    def render_prompt(self):
        """渲染 todo 列表作为 prompt 上下文的一部分。"""
        return self.render_list()

    def to_dict(self):
        """将 todo 状态导出为字典。"""
        return {"next_id": int(self.state.get("next_id", 1)), "items": [dict(item) for item in self.state.get("items", [])]}

    def _record_change(self, action, item):
        """记录 todo 变更事件并持久化 session。"""
        payload = {"action": action, "todo": dict(item)}
        task_state = getattr(self.runtime, "current_task_state", None)
        if task_state is not None:
            task_state.todo_changes.append(payload)
        self.runtime.session_event_bus.emit("todo_changed", payload)
        self.runtime.session_path = self.runtime.session_store.save(self.runtime.session)


def _clean_status(value):
    """校验并标准化 todo 状态值。"""
    status = str(value or "pending").strip()
    if status not in VALID_STATUS:
        raise ValueError(f"status must be one of {', '.join(sorted(VALID_STATUS))}")
    return status


def _clean_priority(value):
    """校验并标准化 todo 优先级值。"""
    priority = str(value or "normal").strip()
    if priority not in VALID_PRIORITY:
        raise ValueError(f"priority must be one of {', '.join(sorted(VALID_PRIORITY))}")
    return priority
