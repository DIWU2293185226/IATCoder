"""可选的沙盒运行支持。

提供 bubblewrap 沙盒，用于安全地执行 run_shell 命令。"""

from .config import SandboxConfig, resolve_sandbox_config
from .runner import SandboxRunner

__all__ = ["SandboxConfig", "SandboxRunner", "resolve_sandbox_config"]
