"""DeepSeek API 联机测试。

用法：
  D:/Anaconda/python.exe -s -m pytest tests/test_deepseek_live.py -v --tb=short

注意：这需要消耗 DeepSeek API 额度，非必要不要频繁运行。
"""

import os
import sys
import json
from pathlib import Path

import pytest

# --- 从 key.md 读取 API key ---
KEY_FILE = Path(__file__).resolve().parent.parent / "key.md"
API_KEY = KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else ""

# --- 只在显式标记的测试中使用真实 API ---
pytestmark = pytest.mark.skipif(
    not API_KEY,
    reason="需要 key.md 中的 DeepSeek API key 才能运行",
)


def test_deepseek_model_client_basic_completion():
    """测试 DeepSeekModelClient 基本完成能力——发一条简单请求，确认能拿到文本回复。"""
    from iatcoder.models import DeepSeekModelClient

    client = DeepSeekModelClient(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key=API_KEY,
        temperature=0.1,
        timeout=30,
    )

    # 不启用 prompt cache
    assert client.supports_prompt_cache is False

    text = client.complete(
        prompt="Reply with only the word: hello",
        max_new_tokens=20,
    )

    assert isinstance(text, str), f"Expected string, got {type(text)}"
    assert len(text) > 0, "Response should not be empty"
    assert "hello" in text.lower(), f"Expected 'hello' in response, got: {text}"
    print(f"\n  Response: {text!r}")

    # 检查 usage 元数据
    meta = client.last_completion_metadata
    assert isinstance(meta, dict), f"Expected dict metadata, got {type(meta)}"
    print(f"  Input tokens: {meta.get('input_tokens')}")
    print(f"  Output tokens: {meta.get('output_tokens')}")
    print(f"  Total tokens: {meta.get('total_tokens')}")
    assert meta.get("output_tokens", 0) > 0, "Should have output tokens"
    assert meta.get("input_tokens", 0) > 0, "Should have input tokens"


def test_deepseek_model_client_multiturn_style():
    """测试 DeepSeek 模型能否理解工具调用格式——模拟一个简单的 agent 场景。"""
    from iatcoder.models import DeepSeekModelClient

    client = DeepSeekModelClient(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key=API_KEY,
        temperature=0.1,
        timeout=30,
    )

    prompt = """You are a coding agent. Reply with exactly:
<tool>{"name":"read_file","args":{"path":"main.py","start":1,"end":10}}</tool>"""

    text = client.complete(prompt, max_new_tokens=100)
    assert isinstance(text, str) and len(text) > 0
    assert "<tool>" in text, f"Expected <tool> in response, got: {text}"
    assert "read_file" in text, f"Expected read_file in response, got: {text}"
    print(f"\n  Tool response: {text!r}")
    print(f"  Total tokens used: {client.last_completion_metadata.get('total_tokens')}")


def test_deepseek_cli_build_agent():
    """测试通过 CLI 的 build_agent 使用 deepseek provider 能正确组装 client。"""
    from iatcoder.cli import build_arg_parser, build_agent
    from iatcoder.models import DeepSeekModelClient

    parser = build_arg_parser()
    args = parser.parse_args([
        "--provider", "deepseek",
        "--model", "deepseek-chat",
        "--base-url", "https://api.deepseek.com",
        "hello",
    ])

    # 注入 API key
    os.environ["DEEPSEEK_API_KEY"] = API_KEY
    try:
        agent = build_agent(args)
        assert isinstance(agent.model_client, DeepSeekModelClient)
        assert agent.model_client.model == "deepseek-chat"
        assert "api.deepseek.com" in agent.model_client.base_url
        print(f"\n  Agent model: {agent.model_client.model}")
        print(f"  Agent provider: {type(agent.model_client).__name__}")
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)


def test_deepseek_through_full_agent_ask():
    """完整的 agent.ask() 集成测试——从 prompt 组装到模型调用再到结果解析。"""
    from iatcoder.models import DeepSeekModelClient
    from iatcoder.runtime import IATCoder, SessionStore
    from iatcoder.workspace import WorkspaceContext
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "README.md").write_text("# Test Project\n", encoding="utf-8")

        client = DeepSeekModelClient(
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=API_KEY,
            temperature=0.1,
            timeout=30,
        )
        workspace = WorkspaceContext.build(tmp)
        store = SessionStore(tmp / ".iatcoder" / "sessions")
        agent = IATCoder(
            model_client=client,
            workspace=workspace,
            session_store=store,
            max_steps=1,
            max_new_tokens=100,
            approval_policy="auto",
        )

        answer = agent.ask("Reply with only the word: deepseek-test")
        assert isinstance(answer, str) and len(answer) > 0
        print(f"\n  Agent answer: {answer!r}")
        print(f"  Steps used: {agent.current_task_state.tool_steps}")
        print(f"  Stop reason: {agent.current_task_state.stop_reason}")
        meta = getattr(agent, "last_completion_metadata", {})
        if meta:
            print(f"  Total tokens: {meta.get('total_tokens')}")
