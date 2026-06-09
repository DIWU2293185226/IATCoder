"""plan mode 工具定义。

enter_plan_mode / exit_plan_mode 让模型可以主动进入和退出规划模式，
在规划模式下写操作受限，只能修改 plan 工件。"""

PLAN_TOOL_SPECS = {
    "enter_plan_mode": {
        "schema": {"topic": "str", "path": "str?"},
        "risky": False,
        "description": "Enter plan mode for a named planning topic.",
    },
    "exit_plan_mode": {
        "schema": {},
        "risky": False,
        "description": "Exit plan mode and return to default runtime mode.",
    },
}

PLAN_TOOL_EXAMPLES = {
    "enter_plan_mode": '<tool>{"name":"enter_plan_mode","args":{"topic":"Refactor auth"}}</tool>',
    "exit_plan_mode": '<tool>{"name":"exit_plan_mode","args":{}}</tool>',
}


def validate_plan_tool(name, args):
    if name == "enter_plan_mode" and not str(args.get("topic", "")).strip():
        raise ValueError("topic must not be empty")


def tool_enter_plan_mode(agent, args):
    path = agent.enter_plan_mode(args["topic"], path=args.get("path"))
    return f"mode: plan\nplan path: {path}"


def tool_exit_plan_mode(agent, args):
    agent.exit_plan_mode()
    return "mode: default"
