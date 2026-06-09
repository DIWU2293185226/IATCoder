"""Plan mode 策略。

进入 plan 模式后模型只能读取文件和写入指定的 plan 工件，
完成规划后写回 plan 文件再返回 final 回答。"""

import re


def _slug(value):
    """将字符串转换为 URL 友好的 slug 格式。"""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value).strip().lower()).strip("-")
    return slug or "plan"


class PlanModeManager:
    def __init__(self, runtime):
        """初始化 plan mode 管理器，绑定 runtime。"""
        self.runtime = runtime

    @property
    def state(self):
        """获取或初始化运行时模式状态。"""
        return self.runtime.session.setdefault("runtime_mode", {"mode": "default"})

    @property
    def mode(self):
        """获取当前运行时模式名。"""
        return str(self.state.get("mode", "default") or "default")

    @property
    def plan_path(self):
        """获取当前 plan 工件路径。"""
        return str(self.state.get("plan_path", "") or "")

    def enter(self, topic, path=None):
        """切换到 plan 模式，设置 plan 主题和路径。"""
        plan_path = _plan_path(topic, path)
        self.runtime.session["runtime_mode"] = {
            "mode": "plan",
            "topic": str(topic or ""),
            "plan_path": plan_path,
        }
        self.runtime.set_tool_profile("plan")
        self.runtime.session_path = self.runtime.session_store.save(
            self.runtime.session
        )
        self.runtime.refresh_prefix(force=True)
        self.runtime.session_event_bus.emit(
            "runtime_mode_changed",
            {"mode": "plan", "plan_path": plan_path, "topic": str(topic or "")},
        )
        return plan_path

    def exit(self):
        """退出 plan 模式，恢复到默认模式。"""
        previous = dict(self.state)
        self.runtime.session["runtime_mode"] = {"mode": "default"}
        self.runtime.set_tool_profile("default")
        self.runtime.session_path = self.runtime.session_store.save(
            self.runtime.session
        )
        self.runtime.refresh_prefix(force=True)
        self.runtime.session_event_bus.emit(
            "runtime_mode_changed",
            {
                "mode": "default",
                "previous_mode": previous.get("mode", "default"),
                "plan_path": previous.get("plan_path", ""),
            },
        )

    def can_finish(self):
        """判断是否允许返回 final 回答（plan 模式需要先写 plan 文件）。"""
        if self.mode != "plan":
            return True
        path = self.runtime.path(self.plan_path)
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())

    def final_notice(self):
        """返回 plan 模式下 final 回答前的提示文本。"""
        return f"Plan mode requires writing the active plan artifact before final answer: {self.plan_path}"

    def prompt_text(self):
        """返回 plan 模式的 prompt 约束文本。"""
        if self.mode != "plan":
            return ""
        return (
            "Runtime mode: plan\n"
            f"- Active plan artifact: {self.plan_path}\n"
            "- You may inspect files, but writes must target only the active plan artifact.\n"
            "- You may launch Explore subagents, but not write-capable worker subagents.\n"
            "- Use todo tools to keep the task ledger current.\n"
            "- Return a final answer only after the active plan artifact has been written."
        )


PlanModeController = PlanModeManager


_PLAN_DIR_MARKER = "/.iatcoder/plans/"


def _plan_path(topic, path=None):
    """根据 topic 或用户提供的 path 规范化 plan 文件路径。"""
    if path:
        value = str(path).strip()
        # 模型有时给绝对路径，如 /Users/u/repo/.iatcoder/plans/foo；自动把它相对化。
        if value.startswith("/") and _PLAN_DIR_MARKER in value:
            value = value[value.index(_PLAN_DIR_MARKER) + 1 :]
        if value.startswith("./"):
            value = value[2:]
    else:
        value = f".iatcoder/plans/{_slug(topic)}-plan.md"
    if (
        not value.startswith(".iatcoder/plans/")
        or value.endswith("/")
        or ".." in value.split("/")
    ):
        raise ValueError("plan path must stay under .iatcoder/plans/")
    return value
