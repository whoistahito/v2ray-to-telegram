"""
v2ray-configs parser
Repo: https://github.com/MatinGhanbari/v2ray-configs
Updated: every ~2 hours automatically

Files: subscriptions/v2ray/subs/sub1.txt – sub39.txt
Format: plain text, lines starting with # are comments, one config per line.
Protocols: vless://, vmess://, ss://, trojan://, hy2://, hysteria2://, tuic://, etc.

(subscriptions/base64/ and subscriptions/filtered/ are redundant copies — skipped.)
"""

import json
import urllib.request

REPO = "MatinGhanbari/v2ray-configs"
SUBS_DIR = "subscriptions/v2ray/subs"
GITHUB_API_SUBS = f"https://api.github.com/repos/{REPO}/contents/{SUBS_DIR}"

PROTOCOLS = (
    "vless://", "vmess://", "ss://", "trojan://",
    "hy2://", "hysteria2://", "hysteria://", "tuic://",
)


def _github_get(url: str) -> object:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "v2ray-bot", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _fetch_raw(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "v2ray-bot"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _fetch_blob(sha: str) -> bytes:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/blobs/{sha}",
        headers={"User-Agent": "v2ray-bot", "Accept": "application/vnd.github.raw+json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _extract_configs(raw: bytes) -> list[str]:
    """Extract valid proxy config lines from plain-text bytes."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and any(line.strip().startswith(p) for p in PROTOCOLS)
    ]


def list_files() -> list[dict]:
    """Return [{name, sha, download_url}] for all sub*.txt files."""
    entries = _github_get(GITHUB_API_SUBS)
    return [
        {"name": e["name"], "sha": e["sha"], "download_url": e["download_url"]}
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".txt")
    ]


def fetch_configs(download_url: str) -> list[str]:
    return _extract_configs(_fetch_raw(download_url))


def fetch_configs_by_sha(sha: str) -> list[str]:
    return _extract_configs(_fetch_blob(sha))


def find_new_configs(old_sha: str, new_sha: str) -> list[str]:
    old_set = set(fetch_configs_by_sha(old_sha))
    return [c for c in fetch_configs_by_sha(new_sha) if c not in old_set]
