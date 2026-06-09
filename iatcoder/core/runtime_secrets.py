"""运行时密钥脱敏和 shell 环境管理。

自动识别和脱敏 API key、token 等敏感信息，
防止它们出现在 trace、report 或 prompt 上下文中。"""

import os

SENSITIVE_ENV_NAME_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
REDACTED_VALUE = "<redacted>"


class RuntimeSecretsMixin:
    @staticmethod
    def looks_sensitive_env_name(name):
        """判断环境变量名是否看起来像敏感信息（启发式）。"""
        upper = str(name).upper()
        return any(upper == marker or upper.endswith(marker) or upper.endswith(f"_{marker}") for marker in SENSITIVE_ENV_NAME_MARKERS)

    def is_secret_env_name(self, name):
        """判断环境变量名是否属于已配置或自动识别的密钥。"""
        upper = str(name).upper()
        return upper in self.secret_env_names or self.looks_sensitive_env_name(upper)

    def configured_secret_env_items(self):
        """列出已在配置中明确声明的密钥环境变量。"""
        items = [(name, value) for name, value in os.environ.items() if str(name).upper() in self.secret_env_names and value]
        items.sort(key=lambda item: item[0])
        return items

    def detected_secret_env_items(self):
        """列出所有被识别为密钥的环境变量（含自动检测）。"""
        items = [(name, value) for name, value in os.environ.items() if self.is_secret_env_name(name) and value]
        items.sort(key=lambda item: item[0])
        return items

    def secret_env_summary(self):
        """返回已配置密钥的摘要信息。"""
        names = [name for name, _ in self.configured_secret_env_items()]
        return {"secret_env_count": len(names), "secret_env_names": names}

    def detected_secret_env_summary(self):
        """返回所有检测到密钥的摘要信息。"""
        names = [name for name, _ in self.detected_secret_env_items()]
        return {"secret_env_count": len(names), "secret_env_names": names}

    def redact_text(self, text):
        """用占位符替换文本中所有密钥值。"""
        text = str(text)
        for _, value in sorted(self.detected_secret_env_items(), key=lambda item: len(item[1]), reverse=True):
            text = text.replace(value, REDACTED_VALUE)
        return text

    def redact_artifact(self, value, key=None):
        """递归地脱敏字典/列表/字符串中的密钥值。"""
        if key and self.is_secret_env_name(key):
            return REDACTED_VALUE
        if isinstance(value, dict):
            return {str(item_key): self.redact_artifact(item_value, key=item_key) for item_key, item_value in value.items()}
        if isinstance(value, list):
            return [self.redact_artifact(item, key=key) for item in value]
        if isinstance(value, tuple):
            return [self.redact_artifact(item, key=key) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def shell_env(self):
        """构建子进程 shell 环境（仅含白名单变量）。"""
        env = {name: os.environ[name] for name in self.shell_env_allowlist if name in os.environ}
        env["PWD"] = str(self.root)
        if "PATH" not in env and os.environ.get("PATH"):
            env["PATH"] = os.environ["PATH"]
        return env
