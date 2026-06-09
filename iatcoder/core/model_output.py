"""模型输出解析：将模型返回的纯文本解析为工具调用或最终回答。

Iatcoder 使用纯文本协议，而非 JSON function calling：
#   <tool>{"name":"xxx","args":{...}}</tool>  -> tool 调用
#   <tool name="xxx" path="..."><content>...</content></tool>  -> XML 风格
#   <final>answer</final>  -> 最终回答
#   (其它格式)  -> retry
# parse() 是 Engine.run_turn() 中模型调用后的第一道工序.
"""

import json
import re


def parse(raw):
    """解析模型返回的原始文本, 返回 (kind, payload).

    规则:
    - 优先匹配 <tool...>...</tool> -> ("tool", {...}) 或 ("tools", [{...}, ...])
    - 其次匹配 <final>...</final> -> ("final", "answer text")
    - 都不匹配 -> ("retry", "错误提示") 让模型重试

    注意: 如果文本同时包含 <tool 和 <final>, tool 优先 (只有 final 出现在更前面时才取 final).
    """
    raw = str(raw)
    if "<tool" in raw and (
        "<final>" not in raw or raw.find("<tool") < raw.find("<final>")
    ):
        parsed = parse_tool_blocks(raw)
        if isinstance(parsed, str):
            return "retry", retry_notice(parsed)
        if parsed:
            return _tool_kind(parsed)

    if "<final>" in raw:
        return "final", extract(raw, "final")

    if not raw.strip():
        return "retry", retry_notice("empty response")
    return "retry", retry_notice("missing <tool> or <final> tag")


def retry_notice(problem=None):
    detail = f" Problem: {problem}." if problem else ""
    return (
        "Your previous response could not be executed."
        f"{detail} Return one or more valid <tool> calls, or one <final> answer."
    )


def normalize_tool_payload(payload):
    if isinstance(payload, list):
        if not payload:
            return "tool JSON list must not be empty"
        normalized = []
        for item in payload:
            parsed = normalize_tool_payload(item)
            if isinstance(parsed, str):
                return parsed
            normalized.extend(parsed)
        return normalized
    if not isinstance(payload, dict) or "name" not in payload:
        return "tool JSON must be an object with name and args"
    args = payload.get("args", {})
    if not isinstance(args, dict):
        return "tool args must be an object"
    return [{"name": payload["name"], "args": args}]


def parse_tool_blocks(raw):
    tools = []
    errors = []
    for match in re.finditer(
        r"<tool\b(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", str(raw), flags=re.DOTALL
    ):
        attrs = parse_attrs(match.group("attrs"))
        if attrs.get("name", "").strip():
            parsed_xml = parse_xml_tool_match(match)
            if parsed_xml:
                tools.append(parsed_xml)
            continue
        body = match.group("body").strip()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            errors.append("tool payload must be valid JSON or supported XML")
            continue
        parsed_json = normalize_tool_payload(payload)
        if isinstance(parsed_json, str):
            errors.append(parsed_json)
            continue
        tools.extend(parsed_json)
    if tools:
        return tools
    if errors:
        return errors[0]
    return []


def _tool_kind(tools):
    if len(tools) == 1:
        return "tool", tools[0]
    return "tools", tools


def parse_xml_tools(raw):
    tools = []
    for match in re.finditer(
        r"<tool\b(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", str(raw), flags=re.DOTALL
    ):
        parsed = parse_xml_tool_match(match)
        if parsed:
            tools.append(parsed)
    return tools


def parse_xml_tool(raw):
    match = re.search(
        r"<tool\b(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", str(raw), flags=re.DOTALL
    )
    if not match:
        return None
    return parse_xml_tool_match(match)


def parse_xml_tool_match(match):
    attrs = parse_attrs(match.group("attrs"))
    body = match.group("body")
    name = attrs.get("name", "").strip()
    if not name:
        return None
    args = {key: value for key, value in attrs.items() if key != "name"}
    for tag in ("content", "old_text", "new_text"):
        value = extract_raw(body, tag)
        if value is not None:
            args[tag] = value
    if name == "write_file" and "content" not in args and body.strip():
        args["content"] = body
    return {"name": name, "args": args}


def parse_attrs(text):
    attrs = {}
    for key, value in re.findall(
        r'([A-Za-z_][A-Za-z0-9_-]*)="(.*?)"', text, flags=re.DOTALL
    ):
        attrs[key] = value
    return attrs


def extract(text, tag):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL)
    if not match:
        return text.strip()
    return match.group(1).strip()


def extract_raw(text, tag):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL)
    if not match:
        return None
    return match.group(1)
