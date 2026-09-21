from pathlib import Path

import yaml

PRESETS = {
    "qq": ("imap.qq.com", 993),
    "163": ("imap.163.com", 993),
    "126": ("imap.126.com", 993),
    "gmail": ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),
}

# 网易系服务器要求登录后立刻上报客户端标识，否则拒绝 SELECT 并回 "Unsafe Login"
NEEDS_IMAP_ID = {"163", "126"}


class ConfigError(Exception):
    pass


class Mailbox:
    def __init__(self, raw, secrets):
        self.name = raw.get("name") or raw.get("email", "mailbox")
        self.provider = (raw.get("provider") or "custom").lower()
        self.email = raw.get("email")
        self.folder = raw.get("folder") or "INBOX"
        self.needs_imap_id = self.provider in NEEDS_IMAP_ID

        if not self.email:
            raise ConfigError(f"[{self.name}] 缺少 email")

        host, port = PRESETS.get(self.provider, (None, 993))
        self.host = raw.get("host") or host
        self.port = int(raw.get("port") or port)
        if not self.host:
            raise ConfigError(f"[{self.name}] provider={self.provider} 需要显式配置 host")

        env_key = raw.get("password_env")
        if not env_key:
            raise ConfigError(f"[{self.name}] 缺少 password_env")
        self.password = secrets.get(env_key)
        if not self.password:
            raise ConfigError(f"[{self.name}] .env 里没有找到 {env_key}，请填入邮箱授权码")


class Config:
    def __init__(self, root: Path, data: dict, secrets: dict):
        self.root = root
        self._raw_mailboxes = data.get("mailboxes") or []
        self._secrets = secrets

        output = data.get("output") or {}
        self.excel_path = self._resolve(output.get("excel", "data/invoices.xlsx"))
        self.pdf_dir = self._resolve(output.get("pdf_dir", "data/pdf"))
        self.state_path = self._resolve("data/state.json")
        self.log_dir = self._resolve("data/logs")
        self.browser_profile = self._resolve("data/browser-profile")

        fetch = data.get("fetch") or {}
        self.link_keywords = [k.lower() for k in fetch.get("link_keywords") or []]
        self.link_exclude = [k.lower() for k in fetch.get("link_exclude") or []]
        self.http_timeout = int(fetch.get("http_timeout", 30))
        self.browser_timeout = int(fetch.get("browser_timeout", 120))
        self.use_browser = bool(fetch.get("use_browser", True))
        self.browser_channel = str(fetch.get("browser_channel", "auto")).lower()

        ocr = data.get("ocr") or {}
        scripts_dir = Path(ocr.get("scripts_dir", "")) if ocr.get("scripts_dir") else None
        self.ocr_dir = (
            scripts_dir if ocr.get("enabled") and scripts_dir and scripts_dir.exists() else None
        )

    @property
    def mailboxes(self):
        if not self._raw_mailboxes:
            raise ConfigError("config.yaml 里没有配置任何 mailboxes")
        return [Mailbox(raw, self._secrets) for raw in self._raw_mailboxes]

    def _resolve(self, value) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path


def _load_secrets(env_path: Path) -> dict:
    secrets = {}
    if not env_path.exists():
        return secrets
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        secrets[key.strip()] = value.strip().strip('"').strip("'")
    return secrets


def load_config(config_path: Path) -> Config:
    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigError(f"找不到配置文件 {config_path}")
    root = config_path.parent
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return Config(root, data, _load_secrets(root / ".env"))
