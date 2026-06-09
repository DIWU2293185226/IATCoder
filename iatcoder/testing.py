"""测试辅助工具：可预测输出的 ScriptedModelClient。

测试时用这个 client 替代真实的 LLM provider，
这样 runtime 行为是确定性的，不依赖外部 API。"""

from .providers.base import ModelResult


class ScriptedModelClient:
    def __init__(self, outputs):
        """初始化脚本化模型客户端。"""
        self.outputs = list(outputs)
        self.prompts = []
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}

    def complete(self, prompt, max_new_tokens, **kwargs):
        """从预设输出列表中返回下一个结果。"""
        self.prompts.append(prompt)
        if not getattr(self, "last_completion_metadata", None):
            self.last_completion_metadata = {}
        if not self.outputs:
            raise RuntimeError("scripted model ran out of outputs")
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output

    def complete_result(self, prompt, max_new_tokens, **kwargs):
        """返回封装为 ModelResult 的预设输出。"""
        return ModelResult(
            text=self.complete(prompt, max_new_tokens, **kwargs),
            metadata=dict(self.last_completion_metadata),
        )
