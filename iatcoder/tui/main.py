from __future__ import annotations

"""TUI 独立启动入口。提供 main() 函数供 `iatcoder tui` 命令调用，
通过 Textual App.run() 启动交互界面。"""

import sys

from iatcoder.cli import build_agent, build_arg_parser
from iatcoder.tui.app import IatcoderTuiApp


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.prompt:
        print("iatcoder-tui does not accept one-shot prompts; start the TUI and type there.", file=sys.stderr)
        return 2
    agent = build_agent(args)
    IatcoderTuiApp(agent).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
