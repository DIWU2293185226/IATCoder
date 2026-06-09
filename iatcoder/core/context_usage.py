"""上下文用量估算。

基于字符数估算 token 用量，让 trace/report 能呈现
每轮 prompt 的上下文占用情况。"""


DEFAULT_CONTEXT_WINDOW = 200_000
TOKEN_ESTIMATION_METHOD = "chars_div_4"


def estimate_tokens(chars):
    """根据字符数估算 token 数量。"""
    return max(0, (int(chars) + 3) // 4)


class ContextUsageAnalyzer:
    def __init__(self, agent):
        """初始化上下文用量分析器。"""
        self.agent = agent

    def analyze(self, rendered):
        """分析已渲染 prompt 的上下文用量。"""
        tools_chars = self._tools_chars()
        sections = {}
        for name, section in rendered.items():
            key = "current_request" if name == "current_request" else name
            chars = int(section.rendered_chars)
            if key == "prefix":
                chars = max(0, chars - tools_chars)
            sections[key] = {
                "chars": chars,
                "tokens": estimate_tokens(chars),
            }
        sections["tools"] = {
            "chars": tools_chars,
            "tokens": estimate_tokens(tools_chars),
        }
        total = sum(section["tokens"] for section in sections.values())
        window = self._context_window()
        reserved = int(getattr(self.agent, "max_new_tokens", 0) or 0)
        return {
            "estimation_method": TOKEN_ESTIMATION_METHOD,
            "model": str(getattr(getattr(self.agent, "model_client", None), "model", "")),
            "context_window": window,
            "reserved_output_tokens": reserved,
            "total_estimated_tokens": total,
            "sections": sections,
            "free_tokens": window - total - reserved,
            "auto_compact_threshold": int(window * 0.8),
        }

    def _context_window(self):
        """根据模型名称推断上下文窗口大小。"""
        model = str(getattr(getattr(self.agent, "model_client", None), "model", "")).lower()
        if "1m" in model or "1000000" in model:
            return 1_000_000
        return DEFAULT_CONTEXT_WINDOW

    def _tools_chars(self):
        """计算工具描述所占的字符数。"""
        total = 0
        for name, tool in self.agent.available_tools().items():
            fields = ", ".join(f"{key}: {value}" for key, value in tool.schema.items())
            risk = "approval required" if tool.risky else "safe"
            total += len(f"- {name}({fields}) [{risk}] {tool.description}\n")
        return total
