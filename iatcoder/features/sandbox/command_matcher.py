"""沙盒排除命令的模式匹配。"""

from fnmatch import fnmatch


def command_is_excluded(command, patterns):
    command = str(command or "").strip()
    return any(fnmatch(command, str(pattern)) for pattern in patterns or ())
