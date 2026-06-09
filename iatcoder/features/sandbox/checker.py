"""沙盒后端可用性检查。"""


class SandboxChecker:
    def __init__(self, which):
        """初始化沙盒检查器。"""
        self.which = which

    def backend_path(self, backend):
        """获取沙盒后端可执行文件路径。"""
        backend = "bubblewrap" if backend == "auto" else backend
        if backend in {"none", "off"}:
            return ""
        if backend == "bubblewrap":
            return self.which("bwrap") or ""
        return ""
