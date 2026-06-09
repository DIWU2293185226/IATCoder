"""工具抽象基类。

RegisteredTool 封装工具的名称、参数 schema、风险等级和执行函数。
ToolResult 是统一的结果包装。"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    schema: dict
    description: str
    risky: bool
    runner: Callable[[dict], str]

    @property
    def read_only(self):
        return not self.risky

    def execute(self, args):
        """执行工具并返回 ToolResult。"""
        result = self.runner(args)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(content=str(result))

    def __getitem__(self, key):
        """字典式访问工具属性或运行器。"""
        if key == "run":
            return self.runner
        return getattr(self, key)
