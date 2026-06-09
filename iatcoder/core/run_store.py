"""运行工件持久化存储。

session.json 负责保存"可恢复的会话状态"；
RunStore 负责保存"单次运行的审计工件"（task_state、trace、report）。
两者分开后，恢复现场和复盘证据不会混在一起。"""

import json
import tempfile
from pathlib import Path


def _run_id(value):
    if hasattr(value, "run_id"):
        return value.run_id
    return str(value)


class RunStore:
    def __init__(self, root):
        """初始化 RunStore，指定工件根目录"""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id):
        """获取指定 run 的目录路径"""
        return self.root / _run_id(run_id)

    def task_state_path(self, run_id):
        """获取 task_state.json 文件路径"""
        return self.run_dir(run_id) / "task_state.json"

    def trace_path(self, run_id):
        """获取 trace.jsonl 文件路径"""
        return self.run_dir(run_id) / "trace.jsonl"

    def report_path(self, run_id):
        """获取 report.json 文件路径"""
        return self.run_dir(run_id) / "report.json"

    def artifacts_dir(self, run_id):
        """获取 artifacts 子目录路径"""
        return self.run_dir(run_id) / "artifacts"

    def start_run(self, task_state):
        """开始一次新 run，创建目录并写入初始状态"""
        # 每次 ask() 都会生成一个 run 目录。
        # 这样一次用户请求对应一组独立工件，后续排查更容易。
        run_dir = self.run_dir(task_state)
        run_dir.mkdir(parents=True, exist_ok=True)
        self.write_task_state(task_state)
        return run_dir

    def write_task_state(self, task_state):
        """原子写入 task_state.json"""
        path = self.task_state_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, task_state.to_dict())
        return path

    def append_trace(self, task_state, event):
        """追加一条事件到 trace.jsonl"""
        path = self.trace_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        # trace 采用 jsonl 追加写入，原因是 agent 运行过程是流式事件序列，
        # 逐条落盘比"最后一次性写整份 trace"更稳，也更适合调试。
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True))
            handle.write("\n")
        return path

    def write_text_artifact(self, task_state, stem, content):
        """将文本内容写入 artifacts 目录"""
        directory = self.artifacts_dir(task_state)
        directory.mkdir(parents=True, exist_ok=True)
        index = len(list(directory.glob(f"{stem}-*.txt"))) + 1
        path = directory / f"{stem}-{index:03d}.txt"
        path.write_text(str(content), encoding="utf-8")
        return path

    def write_report(self, task_state, report):
        """写入运行报告 report.json"""
        path = self.report_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, report)
        return path

    def load_task_state(self, task_id):
        """从磁盘加载 task_state.json"""
        return json.loads(self.task_state_path(task_id).read_text(encoding="utf-8"))

    def load_report(self, task_id):
        """从磁盘加载 report.json"""
        return json.loads(self.report_path(task_id).read_text(encoding="utf-8"))

    def _write_json_atomic(self, path, payload):
        """原子写入 JSON 文件（先写临时文件再替换）"""
        # 原子写：先写临时文件，再 replace。
        # 这样即使中途异常，也不容易留下半截 JSON。
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(path)
