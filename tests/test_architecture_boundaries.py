from pathlib import Path


def test_core_modules_stay_below_entropy_budget():
    root = Path(__file__).resolve().parents[1]
    budgets = {
        "iatcoder/core/runtime.py": 950,
        "iatcoder/core/runtime_events.py": 90,
        "iatcoder/core/runtime_consumers.py": 90,
        "iatcoder/core/artifacts.py": 130,
        "iatcoder/core/task_state.py": 140,
        "iatcoder/core/todo_ledger.py": 120,
        "iatcoder/core/worker_manager.py": 220,
        "iatcoder/core/context_manager.py": 420,
        "iatcoder/core/context_usage.py": 120,
        "iatcoder/core/compact.py": 180,
        "iatcoder/core/engine.py": 470,
        "iatcoder/core/model_errors.py": 100,
        "iatcoder/core/permissions.py": 140,
        "iatcoder/core/tool_policy.py": 90,
        "iatcoder/core/plan_mode.py": 140,
        "iatcoder/core/tool_executor.py": 181,
        "iatcoder/core/tool_profiles.py": 80,
        "iatcoder/core/turn_history.py": 250,
        "iatcoder/features/skills.py": 220,
        "iatcoder/features/skills_bundled.py": 120,
        "iatcoder/features/skills_runtime.py": 140,
        "iatcoder/tools/registry.py": 360,
        "iatcoder/tools/todos.py": 80,
        "iatcoder/tools/agents.py": 90,
    }

    for relative_path, max_lines in budgets.items():
        line_count = len((root / relative_path).read_text(encoding="utf-8").splitlines())
        assert line_count <= max_lines, f"{relative_path} has {line_count} lines, budget is {max_lines}"
