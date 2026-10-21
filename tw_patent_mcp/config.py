"""設定與本機路徑。

憑證只從環境變數讀取；若未設定，依序嘗試下列 .env 檔（不覆蓋既有環境變數）：
1. TW_PATENT_MCP_ENV 指定的檔案
2. 目前工作目錄的 .env
3. ~/.config/tw-patent-mcp/.env

本機狀態（GPSS 鎖檔、下載的 PDF）放在 TW_PATENT_MCP_HOME，預設 ~/.tw-patent-mcp。
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "tw-patent-mcp"


def _candidate_env_files() -> list[Path]:
    files: list[Path] = []
    explicit = os.environ.get("TW_PATENT_MCP_ENV", "").strip()
    if explicit:
        files.append(Path(explicit).expanduser())
    files.append(Path.cwd() / ".env")
    files.append(Path.home() / ".config" / APP_NAME / ".env")
    return files


def load_env(path: Path | None = None) -> Path | None:
    """讀取第一個存在的 .env，回傳實際讀到的路徑。"""
    for env_path in ([path] if path else _candidate_env_files()):
        if not env_path.is_file():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return env_path
    return None


def get(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def home_dir() -> Path:
    raw = get("TW_PATENT_MCP_HOME")
    return Path(raw).expanduser() if raw else Path.home() / f".{APP_NAME}"


def download_dir() -> Path:
    raw = get("TW_PATENT_MCP_DOWNLOAD_DIR")
    return Path(raw).expanduser() if raw else home_dir() / "downloads"


def gpss_lock_file() -> Path:
    return home_dir() / "gpss_lock"


def user_agent() -> str:
    from . import __version__

    return f"{APP_NAME}/{__version__} (+https://github.com/aa0101181514/tw-patent-mcp)"
