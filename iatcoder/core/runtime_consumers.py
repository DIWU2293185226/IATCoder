"""运行时事件的派生消费者。

在 trace 事件发生时自动构建工件图、验证建议和运行时提醒，
不需要运行时主循环手动触发这些计算。"""

from .artifacts import build_artifact_graph, build_verifier_suggestions
from .workspace import clip


class ArtifactGraphConsumer:
    def handle(self, runtime, task_state, event):
        """在 trace 事件触发时构建工件图。"""
        if event.get("event") not in {"tool_executed", "run_finished", "checkpoint_created"}:
            return
        if not task_state.changed_paths and not event.get("artifact_paths"):
            return
        graph = build_artifact_graph(runtime.root, task_state.changed_paths)
        task_state.artifact_graph = graph


class VerifierSuggestionConsumer:
    def handle(self, runtime, task_state, event):
        """在 trace 事件触发时构建验证建议。"""
        if event.get("event") not in {"tool_executed", "run_finished", "checkpoint_created"}:
            return
        graph = task_state.artifact_graph or build_artifact_graph(runtime.root, task_state.changed_paths)
        task_state.verifier_suggestions = build_verifier_suggestions(runtime.root, graph)


class ReminderConsumer:
    def handle(self, runtime, task_state, event):
        """在工具执行失败时记录运行时提醒。"""
        if event.get("event") != "tool_executed":
            return
        status = str(event.get("status", ""))
        if status in {"", "ok"}:
            return
        reminder = {
            "event": "tool_executed",
            "tool": str(event.get("name", "")),
            "status": status,
            "error_type": str(event.get("error_type", "")),
            "message": clip(str(event.get("result", "")), 240),
            "created_at": event.get("created_at", ""),
        }
        task_state.runtime_reminders.append(reminder)


def default_runtime_consumers():
    """返回默认运行时消费者列表。"""
    return [ArtifactGraphConsumer(), VerifierSuggestionConsumer(), ReminderConsumer()]
