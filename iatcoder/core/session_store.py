"""Session JSON 持久化存储。

每个 session 存为一个独立的 JSON 文件，支持
保存/加载/列出/获取最新 session。使用线程锁保证并发安全。"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from .workspace import clip


class SessionStore:
    def __init__(self, root):
        """初始化存储目录，确保目录存在。"""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path(self, session_id):
        """返回 session JSON 文件的完整路径。"""
        return self.root / f"{_safe_session_id(session_id)}.json"

    def event_path(self, session_id):
        """返回 session 事件文件的完整路径。"""
        return self.root / f"{_safe_session_id(session_id)}.events.jsonl"

    def save(self, session):
        """将 session 数据原子写入磁盘。"""
        path = self.path(session["id"])
        payload = json.dumps(session, indent=2)
        with self._lock:
            tmp_path = path.with_name(
                f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            tmp_path.write_text(payload, encoding="utf-8")
            os.replace(tmp_path, path)
        return path

    def load(self, session_id):
        """从磁盘加载指定 session 的 JSON 数据。"""
        with self._lock:
            return json.loads(self.path(session_id).read_text(encoding="utf-8"))

    def latest(self):
        """获取最近修改的 session ID。"""
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime)
        return files[-1].stem if files else None

    def list_sessions(self):
        """列出所有 session 的摘要信息。"""
        rows = []
        for index, path in enumerate(
            sorted(
                self.root.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            ),
            start=1,
        ):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            history = list(session.get("history", []))
            rows.append(
                {
                    "index": index,
                    "id": str(session.get("id", path.stem)),
                    "created_at": str(session.get("created_at", "")),
                    "updated_at": datetime.fromtimestamp(
                        path.stat().st_mtime
                    ).isoformat(timespec="seconds"),
                    "history_count": len(history),
                    "runtime_mode": str(
                        session.get("runtime_mode", {}).get("mode", "default")
                        or "default"
                    ),
                    "workspace_root": str(session.get("workspace_root", "")),
                    "last_final_answer": _last_final_preview(history),
                }
            )
        return rows


def _last_final_preview(history):
    """从对话历史中提取最后一条 assistant 回答的预览。"""
    for item in reversed(history):
        if item.get("role") == "assistant":
            return clip(item.get("content", ""), 80)
    return ""


def _safe_session_id(session_id):
    """校验并安全化 session ID，防止路径穿越。"""
    value = str(session_id or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("invalid session id")
    return value
