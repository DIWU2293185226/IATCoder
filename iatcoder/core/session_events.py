"""会话级别事件总线。

run trace 是单次任务的诊断数据；session event bus 是
整个交互会话的持久化粗粒度时间线，记录 session_started、
model_requested、tool_executed 等关键事件。"""

import json
from pathlib import Path

from .workspace import now


class SessionEventBus:
    def __init__(self, session_id, path, redact=None):
        """初始化会话事件总线。"""
        self.session_id = str(session_id)
        self.path = Path(path)
        self.redact = redact or (lambda value: value)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event, payload=None):
        """发射一条事件记录到持久化文件。"""
        record = dict(payload or {})
        record["event"] = str(event)
        record["session_id"] = self.session_id
        record["created_at"] = now()
        record = self.redact(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, sort_keys=True) + "\n")
        return record
