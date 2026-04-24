"""
v2go parser
Repo: https://github.com/Danialsamadi/v2go
Updated: every ~1 hour automatically ("Fresh Update")

Two sets of files are tracked:

1. Sub*.txt at repo root  (plain text, # comment headers)
   list_files() / fetch_configs() / find_new_configs()

2. Splitted-By-Protocol/*.txt  (base64-encoded, one protocol per file)
   list_split_files() / fetch_split_configs() / find_new_split_configs()
"""

import base64
import json
import urllib.request

REPO = "Danialsamadi/v2go"
GITHUB_API_ROOT = f"https://api.github.com/repos/{REPO}/contents"
GITHUB_API_SPLIT = f"https://api.github.com/repos/{REPO}/contents/Splitted-By-Protocol"

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


def _extract_plain(raw: bytes) -> list[str]:
    """Extract configs from plain-text bytes (# lines are comments)."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and any(line.strip().startswith(p) for p in PROTOCOLS)
    ]


def _extract_base64(raw: bytes) -> list[str]:
    """Decode base64 blob then extract configs."""
    try:
        text = base64.b64decode(raw).decode("utf-8")
    except Exception:
        # Fallback: try plain text
        text = raw.decode("utf-8", errors="replace")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and any(line.strip().startswith(p) for p in PROTOCOLS)
    ]


# ── Sub*.txt (plain text) ─────────────────────────────────────────────────────

def list_files() -> list[dict]:
    """Return [{name, sha, download_url}] for Sub*.txt files at repo root."""
    entries = _github_get(GITHUB_API_ROOT)
    return [
        {"name": e["name"], "sha": e["sha"], "download_url": e["download_url"]}
        for e in entries
        if e["type"] == "file" and e["name"].startswith("Sub") and e["name"].endswith(".txt")
    ]


def fetch_configs(download_url: str) -> list[str]:
    return _extract_plain(_fetch_raw(download_url))


def fetch_configs_by_sha(sha: str) -> list[str]:
    return _extract_plain(_fetch_blob(sha))


def find_new_configs(old_sha: str, new_sha: str) -> list[str]:
    old_set = set(fetch_configs_by_sha(old_sha))
    return [c for c in fetch_configs_by_sha(new_sha) if c not in old_set]


# ── Splitted-By-Protocol/*.txt (base64-encoded) ───────────────────────────────

def list_split_files() -> list[dict]:
    """Return [{name, sha, download_url}] for non-empty protocol files."""
    entries = _github_get(GITHUB_API_SPLIT)
    return [
        {"name": e["name"], "sha": e["sha"], "download_url": e["download_url"]}
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".txt") and e.get("size", 0) > 0
    ]


def fetch_split_configs(download_url: str) -> list[str]:
    return _extract_base64(_fetch_raw(download_url))


def fetch_split_configs_by_sha(sha: str) -> list[str]:
    return _extract_base64(_fetch_blob(sha))


def find_new_split_configs(old_sha: str, new_sha: str) -> list[str]:
    old_set = set(fetch_split_configs_by_sha(old_sha))
    return [c for c in fetch_split_configs_by_sha(new_sha) if c not in old_set]
