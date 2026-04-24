"""
bot.py — V2Ray Config Bot

Polls the v2go GitHub repo for vless:// configs, tests them with xray-core,
and sends the top 10 fastest configs to a Telegram channel each cycle.
"""

import json
import os
import threading
import time

import telebot

from parsers import v2go
from tester import run_tests

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID    = os.environ.get("CHANNEL_ID", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "3600"))
TEST_WORKERS  = int(os.environ.get("TEST_WORKERS", "50"))
TEST_TIMEOUT  = float(os.environ.get("TEST_TIMEOUT", "5.0"))
TOP_N         = int(os.environ.get("TOP_N", "10"))

STATE_FILE    = os.environ.get("STATE_FILE", "data/state.json")
SEND_DELAY    = 0.05

bot = telebot.TeleBot(BOT_TOKEN)


# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Telegram ──────────────────────────────────────────────────────────────────

def _escape_md(text: str) -> str:
    """Escape characters special in Telegram MarkdownV2."""
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, "\\" + ch)
    return text


def send_top10(results: list[tuple[str, float]]) -> None:
    """Send a ranked list of (uri, latency_ms) tuples to Telegram."""
    if not results:
        bot.send_message(CHANNEL_ID, "No working configs found this cycle.")
        return

    header = f"*Top {len(results)} vless configs* \\(by ping\\)\n\n"
    msg = header
    for i, (uri, latency) in enumerate(results, 1):
        line = f"`{_escape_md(uri)}`\n_Ping: {latency:.0f} ms_\n\n"
        # Telegram message limit is 4096 chars; split if needed
        if len(msg) + len(line) > 4000:
            bot.send_message(CHANNEL_ID, msg, parse_mode="MarkdownV2")
            time.sleep(SEND_DELAY)
            msg = ""
        msg += f"*{i}\\.*  " + line
    if msg.strip():
        bot.send_message(CHANNEL_ID, msg, parse_mode="MarkdownV2")


# ── Per-repo SHA tracker ──────────────────────────────────────────────────────

def _sync_repo(state: dict, key: str, parser,
               list_fn: str = "list_files",
               fetch_fn: str = "fetch_configs",
               diff_fn: str = "find_new_configs") -> tuple[dict, list[str]]:
    """
    Sync one repo's file SHAs.
    Returns (updated_repo_state, new_vless_configs).
    Only returns vless:// configs.
    """
    repo_state = state.get(key, {})
    new_configs: list[str] = []

    try:
        files = getattr(parser, list_fn)()
    except Exception as e:
        print(f"[{key}] ERROR listing files: {e}")
        return repo_state, new_configs

    for f in files:
        name       = f["name"]
        remote_sha = f["sha"]
        known_sha  = repo_state.get(name)

        try:
            if known_sha is None:
                print(f"[{key}] First run for {name}")
                configs = getattr(parser, fetch_fn)(f["download_url"])
            elif known_sha != remote_sha:
                print(f"[{key}] Change in {name}: {known_sha[:8]} -> {remote_sha[:8]}")
                configs = getattr(parser, diff_fn)(known_sha, remote_sha)
            else:
                continue  # no change

            vless = [c for c in configs if c.startswith("vless://")]
            new_configs.extend(vless)
            print(f"[{key}] {name}: {len(vless)} new vless configs")
            repo_state[name] = remote_sha

        except Exception as e:
            print(f"[{key}] ERROR processing {name}: {e}")

    return repo_state, new_configs


# ── Main cycle ────────────────────────────────────────────────────────────────

def check_and_test() -> None:
    state = load_state()

    all_new_vless: list[str] = []

    # Collect new vless configs from v2go only
    sources = [
        ("v2go",         v2go,         "list_files",        "fetch_configs",       "find_new_configs"),
        ("v2go_split",   v2go,         "list_split_files",  "fetch_split_configs", "find_new_split_configs"),
    ]

    for key, parser, list_fn, fetch_fn, diff_fn in sources:
        repo_state, new_vless = _sync_repo(state, key, parser, list_fn, fetch_fn, diff_fn)
        state[key] = repo_state
        all_new_vless.extend(new_vless)

    save_state(state)

    if not all_new_vless:
        print("[bot] No new vless configs this cycle.")
        return

    # Deduplicate
    all_new_vless = list(dict.fromkeys(all_new_vless))
    print(f"[bot] {len(all_new_vless)} unique new vless configs to test.")

    # Also re-test previous top 10 so they stay fresh
    prev_top = state.get("last_top10", [])
    to_test = list(dict.fromkeys(prev_top + all_new_vless))

    results = run_tests(to_test, workers=TEST_WORKERS, timeout_s=TEST_TIMEOUT, top_n=TOP_N)

    # Persist current top 10 URIs for next cycle
    state["last_top10"] = [uri for uri, _ in results]
    save_state(state)

    send_top10(results)


# ── Bot commands ──────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    bot.reply_to(
        message,
        "V2Ray Config Bot\n\n"
        "Fetches vless configs from v2go, tests them with xray-core,\n"
        "and sends the top 10 fastest to this channel every poll cycle.\n\n"
        "Sources:\n"
        "  • Danialsamadi/v2go (~1h)\n"
        "    - Sub*.txt at repo root\n"
        "    - Splitted-By-Protocol/vless*.txt\n\n"
        "/fetch  — run a cycle now\n"
        "/status — show tracked file counts\n"
        "/top    — show last top 10 (no re-test)",
    )


@bot.message_handler(commands=["fetch"])
def cmd_fetch(message):
    bot.reply_to(message, "Starting fetch + test cycle...")
    check_and_test()
    bot.reply_to(message, "Cycle complete.")


@bot.message_handler(commands=["status"])
def cmd_status(message):
    state = load_state()
    lines = []
    for key in ("v2go", "v2go_split"):
        val = state.get(key, {})
        if isinstance(val, dict):
            lines.append(f"*{key}*: {len(val)} file(s) tracked")
    text = "\n".join(lines) if lines else "No state yet."
    bot.reply_to(message, text, parse_mode="Markdown")


@bot.message_handler(commands=["top"])
def cmd_top(message):
    state = load_state()
    prev = state.get("last_top10", [])
    if not prev:
        bot.reply_to(message, "No results yet — run /fetch first.")
        return
    text = "*Last top 10 (cached, not re-tested):*\n\n"
    for i, uri in enumerate(prev, 1):
        text += f"{i}. `{uri}`\n\n"
    bot.reply_to(message, text, parse_mode="Markdown")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def polling_loop():
        print(f"[INFO] Polling every {POLL_INTERVAL}s.")
        while True:
            try:
                check_and_test()
            except Exception as e:
                print(f"[ERROR] Cycle failed: {e}")
            time.sleep(POLL_INTERVAL)

    threading.Thread(target=polling_loop, daemon=True).start()
    print("[INFO] Bot started.")
    bot.infinity_polling()
