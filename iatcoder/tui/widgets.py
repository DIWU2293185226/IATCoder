from __future__ import annotations

"""TUI 界面组件定义。包含 WelcomeBanner、ChatLog、ToolCard、StatusBar、InputBar、
SlashSuggestions、ConfirmPrompt、AskUserPrompt 等 Textual 组件的实现。"""

import json
from pathlib import Path

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Markdown, Static

from ..commands.slash import SlashCommand, suggest_commands


IATCODER_MARK = [
    r"        /\___/\\",
    r"       (  o o  )",
    r"       /   ^   \\",
    r"      /|       |\\",
]


def format_tool_args(name: str, args: dict | None) -> str:
    """格式化工具调用参数为可读字符串。"""
    args = args or {}
    if name == "run_shell":
        return str(args.get("command", ""))
    if name in {"read_file", "write_file", "patch_file", "list_files"}:
        path = str(args.get("path", "."))
        if name == "write_file":
            return f"{path} ({len(str(args.get('content', '')))} chars)"
        return path
    if name == "search":
        return f"{args.get('pattern', '')} in {args.get('path', '.')}"
    if name == "agent":
        return str(args.get("task", args.get("description", "")))
    if name == "send_message":
        return str(args.get("to", ""))
    if name == "task_stop":
        return str(args.get("task_id", ""))
    return json.dumps(args, ensure_ascii=False, sort_keys=True)


class WelcomeBanner(Static):
    DEFAULT_CSS = """
    WelcomeBanner {
        height: auto;
        margin: 1 1 0 1;
        padding: 1 2;
        background: #15161c;
        color: #f1f3f8;
        border: round #5c7cfa;
    }
    """

    # 初始化欢迎横幅，记录模型名、工作目录和审批模式。
    def __init__(self, model_name: str = "", cwd: str = "", approval: str = "") -> None:
        super().__init__()
        self.model_name = model_name
        self.cwd = cwd
        self.approval = approval

    # 渲染欢迎页面的 Rich Text 内容。
    def render(self) -> Text:
        cwd_name = Path(self.cwd).name + "/" if self.cwd else "-"
        muted = "#8b93a7"
        accent = "#9ec5fe"
        rows = [
            Text.assemble(
                Text("iatcoder", style=f"bold {accent}"),
                Text("  local coding agent", style=muted),
            ),
            Text(""),
        ]
        rows.extend(Text(line, style=accent) for line in IATCODER_MARK)
        rows.extend(
            [
                Text(""),
                Text.assemble(
                    Text("model ", style=muted),
                    Text(self.model_name or "-", style=accent),
                    Text("   approval ", style=muted),
                    Text(self.approval or "-", style=accent),
                    Text("   cwd ", style=muted),
                    Text(cwd_name, style=accent),
                ),
                Text(
                    "type /help for commands, Ctrl+L to clear, Ctrl+Q to quit",
                    style=muted,
                ),
            ]
        )
        return Text("\n").join(rows)


class UserMessage(Static):
    DEFAULT_CSS = """
    UserMessage {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        color: #b7f5c1;
        border-left: thick #2f9e44;
    }
    """

    # 初始化用户消息组件，记录消息内容。
    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content

    # 渲染用户消息，带 ">" 绿色前缀。
    def render(self) -> Text:
        return Text.assemble(
            Text("> ", style="bold green"), Text(self.content, style="green")
        )


class AssistantMessage(Static):
    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #15161c;
        border-left: thick #495057;
    }
    AssistantMessage Markdown {
        height: auto;
        width: 100%;
    }
    """

    # 初始化助手消息组件，记录文本内容。
    def __init__(self, content: str) -> None:
        super().__init__(markup=False)
        self.content = content

    # 组合子组件：生成 Markdown 控件。
    def compose(self):
        yield Markdown(self.content)

    """更新消息内容并刷新 Markdown 显示。"""
    def update_content(self, content: str) -> None:
        self.content = content
        try:
            self.query_one(Markdown).update(content)
        except Exception:
            pass


class ToolCard(Static):
    DEFAULT_CSS = """
    ToolCard {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #14171d;
        border: round #4dabf7;
    }
    ToolCard .tool-output {
        max-height: 14;
        color: #adb5bd;
        padding: 0 1;
        overflow-x: hidden;
    }
    """

    # 初始化工具调用卡片，记录工具名、参数摘要和初始状态。
    def __init__(self, tool_name: str, args_summary: str = "") -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args_summary = args_summary[:120]
        self.status = "running"
        self.output = ""
        self._collapsible: Collapsible | None = None
        self._output_widget: Static | None = None

    # 组合子组件：创建可折叠的输出区域。
    def compose(self):
        self._output_widget = Static("", classes="tool-output")
        self._collapsible = Collapsible(
            self._output_widget, title=self._label(), collapsed=False
        )
        yield self._collapsible

    # 生成折叠面板的标题标签，含状态图标。
    def _label(self) -> str:
        icon = {"running": "...", "success": "OK", "error": "ERR"}.get(
            self.status, ".."
        )
        if self.args_summary:
            return f"[{icon}] {self.tool_name}: {self.args_summary}"
        return f"[{icon}] {self.tool_name}"

    # 刷新折叠面板的标题显示。
    def _refresh_label(self) -> None:
        if self._collapsible is not None:
            self._collapsible.title = self._label()

    """将工具状态置为成功，更新输出并折叠面板。"""
    def set_success(self, output: str = "") -> None:
        self.status = "success"
        self.output = output
        self._refresh_label()
        if self._output_widget is not None:
            self._output_widget.update(_clip(output))
        if self._collapsible is not None:
            self._collapsible.collapsed = True

    """将工具状态置为错误，更新输出并展开面板。"""
    def set_error(self, output: str = "") -> None:
        self.status = "error"
        self.output = output
        self._refresh_label()
        if self._output_widget is not None:
            self._output_widget.update(_clip(output))
        if self._collapsible is not None:
            self._collapsible.collapsed = False


class ConfirmPrompt(Static):
    DEFAULT_CSS = """
    ConfirmPrompt {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: #211d12;
        color: #ffe8a1;
        border: round #f59f00;
    }
    """

    # 初始化确认提示框，记录工具名和参数摘要。
    def __init__(self, tool_name: str, args_summary: str) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args_summary = args_summary
        self.selected = False

    # 渲染确认提示界面，显示 allow/deny 选项。
    def render(self) -> Text:
        allow = "[allow]" if self.selected else " allow "
        deny = " deny " if self.selected else "[deny]"
        return Text.assemble(
            Text("Approve tool call? ", style="bold yellow"),
            Text(self.tool_name, style="yellow"),
            Text(f" {self.args_summary}\n", style="#ffe8a1"),
            Text("Left/Right choose, Enter confirms, Esc denies: ", style="#c9a227"),
            Text(deny, style="bold red"),
            Text("  "),
            Text(allow, style="bold green"),
        )

    # 选择 allow（批准），刷新界面。
    def select_allow(self) -> None:
        self.selected = True
        self.refresh()

    # 选择 deny（拒绝），刷新界面。
    def select_deny(self) -> None:
        self.selected = False
        self.refresh()


class AskUserPrompt(Static):
    DEFAULT_CSS = """
    AskUserPrompt {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: #121f2b;
        color: #d0ebff;
        border: round #4dabf7;
    }
    """

    # 初始化用户提问组件，记录问题和选项列表。
    def __init__(self, question: str, choices: list[str]) -> None:
        super().__init__()
        self.question = question
        self.choices = list(choices or [])
        self.selected_index = 0

    @property
    # 返回当前选中的选项文本。
    def selected_choice(self) -> str:
        if not self.choices:
            return ""
        return self.choices[self.selected_index]

    # 渲染提问界面，高亮当前选中项。
    def render(self) -> Text:
        if not self.choices:
            return Text.assemble(
                Text(self.question + "\n", style="bold #d0ebff"),
                Text("Enter continues, Esc cancels", style="#74c0fc"),
            )
        parts = [Text(self.question + "\n", style="bold #d0ebff")]
        for index, choice in enumerate(self.choices):
            marker = f"[{choice}]" if index == self.selected_index else f" {choice} "
            parts.append(
                Text(
                    marker,
                    style="bold #a5d8ff" if index == self.selected_index else "#74c0fc",
                )
            )
            parts.append(Text("  "))
        parts.append(
            Text("\nLeft/Right choose, Enter confirms, Esc cancels", style="#74c0fc")
        )
        return Text.assemble(*parts)

    # 将选中的选项索引向后移动一位。
    def select_next(self) -> None:
        if self.choices:
            self.selected_index = min(len(self.choices) - 1, self.selected_index + 1)
            self.refresh()

    # 将选中的选项索引向前移动一位。
    def select_previous(self) -> None:
        if self.choices:
            self.selected_index = max(0, self.selected_index - 1)
            self.refresh()


class ChatLog(VerticalScroll):
    DEFAULT_CSS = """
    ChatLog {
        height: 1fr;
        padding: 1 1 0 1;
        background: #0f1117;
        scrollbar-size: 1 1;
    }
    """

    """根据角色添加消息组件（user/assistant/tool）并滚动到底部。"""
    def add_message(self, role: str, content: str, tool_name: str = "") -> Widget:
        if role == "user":
            widget = UserMessage(content)
        elif role == "assistant":
            widget = AssistantMessage(content)
        elif role == "tool":
            widget = ToolCard(tool_name=tool_name, args_summary=content)
        else:
            widget = Static(content)
        self.mount(widget)
        self.call_after_refresh(self.scroll_end, animate=False)
        return widget

    """添加工具调用卡片并滚动到底部。"""
    def add_tool_call(self, name: str, args: dict | None = None) -> ToolCard:
        card = ToolCard(tool_name=name, args_summary=format_tool_args(name, args))
        self.mount(card)
        self.call_after_refresh(self.scroll_end, animate=False)
        return card

    """清空所有聊天消息子组件。"""
    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()


class ThinkingIndicator(Static):
    DEFAULT_CSS = """
    ThinkingIndicator {
        height: 1;
        padding: 0 2;
        color: #8b93a7;
        background: #0f1117;
    }
    ThinkingIndicator.hidden {
        display: none;
    }
    """

    FRAMES = ("thinking", "thinking.", "thinking..", "thinking...")

    # 初始化思考指示器，默认隐藏。
    def __init__(self) -> None:
        super().__init__("")
        self.frame = 0
        self.detail = ""
        self.add_class("hidden")

    # 显示指示器并开始帧动画。
    def show(self, detail: str = "") -> None:
        self.detail = detail
        self.remove_class("hidden")
        self.advance()

    # 隐藏指示器并清空文本。
    def hide(self) -> None:
        self.add_class("hidden")
        self.update("")

    # 更新详细描述文本。
    def set_detail(self, detail: str) -> None:
        self.detail = detail
        self.advance()

    # 推进到下一帧动画并刷新显示。
    def advance(self) -> None:
        label = self.FRAMES[self.frame % len(self.FRAMES)]
        self.frame += 1
        if self.detail:
            label = f"{label}  {self.detail}"
        self.update(label)


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 2;
        background: #1b1f2a;
        color: #c5d1e8;
    }
    """

    # 初始化状态栏，记录对话轮次和上下文信息。
    def __init__(self) -> None:
        super().__init__("")
        self.turns = 0
        self.context_text = "context -"
        self.agent_text = ""

    """更新状态栏显示的 agent 信息（模型、模式、会话）。"""
    def update_agent(self, agent) -> None:
        model = getattr(agent.model_client, "model", "")
        mode = getattr(agent, "runtime_mode", "default")
        session = str(agent.session.get("id", ""))[-10:]
        self.agent_text = f"model {model or '-'} | mode {mode} | session {session}"
        self._render_status()

    """更新对话轮次计数并刷新显示。"""
    def update_turns(self, count: int) -> None:
        self.turns = int(count)
        self._render_status()

    """更新上下文用量信息并刷新显示。"""
    def update_context_usage(self, usage: dict | None) -> None:
        usage = usage or {}
        used = (
            usage.get("total_estimated_tokens")
            or usage.get("used_tokens")
            or usage.get("estimated_tokens")
            or usage.get("total_tokens")
        )
        budget = (
            usage.get("budget")
            or usage.get("max_tokens")
            or usage.get("context_window")
        )
        if used and budget:
            self.context_text = f"context {used}/{budget}"
        elif used:
            self.context_text = f"context {used}"
        else:
            self.context_text = "context -"
        self._render_status()

    # 组合并渲染完整的状态栏文本。
    def _render_status(self) -> None:
        self.update(
            f"{self.agent_text} | turns {self.turns} | {self.context_text}".strip()
        )


class SlashSuggestions(Static):
    DEFAULT_CSS = """
    SlashSuggestions {
        display: none;
        height: auto;
        max-height: 8;
        padding: 0 1;
        background: #111827;
        color: #d8dcff;
        border: round #4b61a8;
    }
    SlashSuggestions.visible {
        display: block;
    }
    """

    # 初始化斜杠命令建议列表（默认隐藏）。
    def __init__(self) -> None:
        super().__init__("")
        self.suggestions: list[SlashCommand] = []
        self.selected_index = 0
        self.visible = False

    """更新建议列表并切换可见状态。"""
    def update_suggestions(
        self, suggestions: list[SlashCommand], selected_index: int = 0
    ) -> None:
        self.suggestions = list(suggestions)
        self.selected_index = max(
            0, min(int(selected_index or 0), max(len(self.suggestions) - 1, 0))
        )
        self.visible = bool(self.suggestions)
        self.set_class(self.visible, "visible")
        self.refresh()

    # 隐藏建议列表（清空并隐藏）。
    def hide_suggestions(self) -> None:
        self.update_suggestions([])

    # 渲染建议列表，高亮当前选中项。
    def render(self) -> Text:
        if not self.suggestions:
            return Text("")
        lines = []
        for index, command in enumerate(self.suggestions):
            marker = ">" if index == self.selected_index else " "
            style = "bold cyan" if index == self.selected_index else "#a7a9bb"
            lines.append(
                Text.assemble(
                    Text(f"{marker} /{command.name:<15}", style=style),
                    Text(command.description, style="#d8dcff"),
                )
            )
        return Text("\n").join(lines)


class InputBar(Static):
    DEFAULT_CSS = """
    InputBar {
        height: auto;
        min-height: 3;
        padding: 0 1 1 1;
        background: #0f1117;
    }
    InputBar Input {
        height: 3;
        border: round #4dabf7;
    }
    """

    # 初始化输入栏，包含输入框、历史记录和斜杠建议。
    def __init__(self) -> None:
        super().__init__()
        self.input = Input(placeholder="Ask iatcoder or type /help")
        self.history: list[str] = []
        self.history_index = 0
        self._slash_suggestions: list[SlashCommand] = []
        self._slash_index = 0

    # 组合子组件：输入框和斜杠建议列表。
    def compose(self):
        yield self.input
        yield SlashSuggestions()

    # 将焦点设置到输入框。
    def focus_input(self) -> None:
        self.input.focus()

    # 设置输入框的忙状态：禁用输入并切换占位文本。
    def set_busy(self, busy: bool) -> None:
        self.input.disabled = bool(busy)
        self.input.placeholder = (
            "iatcoder is working..." if busy else "Ask iatcoder or type /help"
        )

    # 切换到上一条历史输入。
    def history_prev(self) -> None:
        if not self.history:
            return
        self.history_index = max(0, self.history_index - 1)
        self.input.value = self.history[self.history_index]

    # 切换到下一条历史输入。
    def history_next(self) -> None:
        if not self.history:
            return
        self.history_index = min(len(self.history), self.history_index + 1)
        self.input.value = (
            ""
            if self.history_index == len(self.history)
            else self.history[self.history_index]
        )

    # 输入框内容改变时更新斜杠命令建议。
    def on_input_changed(self, event: Input.Changed) -> None:
        self.update_slash_suggestions(event.value)

    """根据输入文本更新斜杠命令建议列表。"""
    def update_slash_suggestions(self, text: str | None = None) -> None:
        text = self.input.value if text is None else str(text)
        self._slash_suggestions = suggest_commands(text)
        self._slash_index = 0
        self.query_one(SlashSuggestions).update_suggestions(
            self._slash_suggestions, self._slash_index
        )

    # 隐藏斜杠命令建议并重置索引。
    def hide_slash_suggestions(self) -> None:
        self._slash_suggestions = []
        self._slash_index = 0
        self.query_one(SlashSuggestions).hide_suggestions()

    """完成当前选中的斜杠命令补全到输入框。"""
    def complete_slash_suggestion(self) -> bool:
        if not self._slash_suggestions:
            return False
        command = self._slash_suggestions[self._slash_index]
        raw = self.input.value
        _, separator, rest = (
            raw[1:].partition(" ") if raw.startswith("/") else ("", "", "")
        )
        suffix = rest if separator else ""
        self.input.value = f"/{command.name} " + (suffix if suffix else "")
        self.input.cursor_position = len(self.input.value)
        self.hide_slash_suggestions()
        return True

    """按方向移动斜杠命令的选中索引。"""
    def move_slash_selection(self, direction: int) -> bool:
        if not self._slash_suggestions:
            return False
        self._slash_index = (self._slash_index + direction) % len(
            self._slash_suggestions
        )
        self.query_one(SlashSuggestions).update_suggestions(
            self._slash_suggestions, self._slash_index
        )
        return True

    # 应用斜杠命令补全（complete_slash_suggestion 的别名）。
    def apply_slash_completion(self) -> bool:
        return self.complete_slash_suggestion()


# 裁剪过长的文本并追加省略号。
def _clip(text: str, limit: int = 1200) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 3] + "..."
