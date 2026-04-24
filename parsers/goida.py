"""
Goida VPN Configs parser
Repo: https://github.com/AvenCores/goida-vpn-configs
Updated: every ~1 hour automatically

Files live in githubmirror/*.txt
Format: plain text or base64-encoded, one config per line.
Config protocols: vless://, vmess://, ss://, trojan://, hy2://, hysteria2://, etc.
Lines starting with # are comments and are skipped.
"""

import base64
import json
import urllib.request

REPO = "AvenCores/goida-vpn-configs"
DIR = "githubmirror"
GITHUB_API_DIR = f"https://api.github.com/repos/{REPO}/contents/{DIR}"

# Protocols we care about
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


def _decode(raw: bytes) -> str:
    """Return text from raw bytes, auto-detecting base64."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")

    # If the content doesn't start with a known protocol or comment,
    # it's likely base64-encoded — try to decode it.
    stripped = text.strip()
    if not stripped.startswith("#") and not any(stripped.startswith(p) for p in PROTOCOLS):
        try:
            decoded = base64.b64decode(stripped).decode("utf-8")
            # Sanity check: decoded content should contain at least one protocol
            if any(p in decoded for p in PROTOCOLS):
                return decoded
        except Exception:
            pass

    return text


def _extract_configs(text: str) -> list[str]:
    """Extract all valid proxy config lines from text."""
    configs = []
    for line in text.splitlines():
        line = line.strip()
        if line and any(line.startswith(p) for p in PROTOCOLS):
            configs.append(line)
    return configs


def list_files() -> list[dict]:
    """Return list of {name, sha, download_url} for all .txt files in githubmirror/."""
    entries = _github_get(GITHUB_API_DIR)
    return [
        {"name": e["name"], "sha": e["sha"], "download_url": e["download_url"]}
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".txt")
    ]


def fetch_configs(download_url: str) -> list[str]:
    """Fetch a file by download URL and return its config lines."""
    raw = _fetch_raw(download_url)
    return _extract_configs(_decode(raw))


def fetch_configs_by_sha(sha: str) -> list[str]:
    """Fetch a file by blob SHA and return its config lines."""
    raw = _fetch_blob(sha)
    return _extract_configs(_decode(raw))


def find_new_configs(old_sha: str, new_sha: str) -> list[str]:
    """Return configs present in new_sha but not in old_sha."""
    old_set = set(fetch_configs_by_sha(old_sha))
    new_configs = fetch_configs_by_sha(new_sha)
    return [c for c in new_configs if c not in old_set]
