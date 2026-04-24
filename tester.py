"""
tester.py — vless:// URI → xray-core ping tester

Flow for each config:
  1. Parse vless:// URI into an xray-core JSON config
  2. Spawn xray-core with that config, listening on a random local SOCKS5 port
  3. Make an HTTP GET through the SOCKS5 proxy and measure response time
  4. Kill xray-core
  5. Return latency in ms, or None on failure

run_tests(configs, workers, timeout_s) tests a list of URI strings in parallel
and returns them sorted by latency.
"""

import json
import os
import random
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, unquote, urlparse

# Path to the xray binary — set via env or default for Docker
XRAY_BIN = os.environ.get("XRAY_BIN", "/usr/local/bin/xray")

# URL used to measure latency (returns 204, tiny response)
PING_URL = "http://www.gstatic.com/generate_204"

# ── URI parser ────────────────────────────────────────────────────────────────

def _free_port() -> int:
    """Return a free local TCP port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def vless_uri_to_xray_config(uri: str, socks_port: int) -> dict | None:
    """
    Parse a vless:// URI and return an xray-core JSON config dict.
    Returns None if the URI cannot be parsed.

    Supported transports: ws, tcp, grpc, httpupgrade, splithttp
    Supported security:   none, tls, reality
    """
    try:
        parsed = urlparse(uri)
        if parsed.scheme != "vless":
            return None

        uuid = parsed.username
        server = parsed.hostname
        port = parsed.port or 443
        params = parse_qs(parsed.query, keep_blank_values=True)

        def p(key: str, default: str = "") -> str:
            vals = params.get(key)
            return unquote(vals[0]) if vals else default

        transport = p("type", "tcp")
        security  = p("security", "none")
        sni       = p("sni") or server
        host      = p("host") or server
        path      = p("path", "/")
        fp        = p("fp", "chrome")
        pbk       = p("pbk")
        sid       = p("sid", "")
        flow      = p("flow", "")
        alpn_raw  = p("alpn")
        alpn      = alpn_raw.split(",") if alpn_raw else ["h2", "http/1.1"]
        service   = p("serviceName", "")  # grpc

        # ── stream settings ───────────────────────────────────────────────────
        if transport == "ws":
            network_settings = {
                "wsSettings": {
                    "path": path,
                    "headers": {"Host": host},
                }
            }
        elif transport == "grpc":
            network_settings = {
                "grpcSettings": {
                    "serviceName": service,
                    "multiMode": False,
                }
            }
        elif transport in ("httpupgrade", "splithttp"):
            network_settings = {
                "httpupgradeSettings": {
                    "path": path,
                    "host": host,
                }
            }
        else:  # tcp / raw
            network_settings = {}

        # ── TLS / Reality settings ────────────────────────────────────────────
        if security == "tls":
            tls_settings = {
                "tlsSettings": {
                    "serverName": sni,
                    "allowInsecure": True,
                    "fingerprint": fp,
                    "alpn": alpn,
                }
            }
        elif security == "reality":
            tls_settings = {
                "realitySettings": {
                    "serverName": sni,
                    "fingerprint": fp,
                    "publicKey": pbk,
                    "shortId": sid,
                    "spiderX": "",
                }
            }
        else:
            tls_settings = {}

        stream_settings = {
            "network": transport if transport not in ("httpupgrade", "splithttp") else "tcp",
            "security": security if security in ("tls", "reality") else "none",
            **network_settings,
            **tls_settings,
        }

        outbound = {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": server,
                    "port": port,
                    "users": [{
                        "id": uuid,
                        "encryption": "none",
                        "flow": flow,
                    }],
                }]
            },
            "streamSettings": stream_settings,
        }

        config = {
            "log": {"loglevel": "none"},
            "inbounds": [{
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }],
            "outbounds": [
                outbound,
                {"protocol": "freedom", "tag": "direct"},
            ],
        }
        return config

    except Exception:
        return None


# ── Single config tester ──────────────────────────────────────────────────────

def _test_one(uri: str, timeout_s: float) -> tuple[str, float | None]:
    """
    Test a single vless:// URI.
    Returns (uri, latency_ms) or (uri, None) on failure.
    """
    socks_port = _free_port()
    config = vless_uri_to_xray_config(uri, socks_port)
    if config is None:
        return uri, None

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        cfg_path = f.name

    proc = None
    try:
        proc = subprocess.Popen(
            [XRAY_BIN, "run", "-config", cfg_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for xray to bind the SOCKS port (up to 2s)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", socks_port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            return uri, None  # xray never started

        # Build a SOCKS5 proxy handler
        proxy_handler = urllib.request.ProxyHandler({
            "http":  f"socks5h://127.0.0.1:{socks_port}",
            "https": f"socks5h://127.0.0.1:{socks_port}",
        })
        opener = urllib.request.build_opener(proxy_handler)

        t0 = time.monotonic()
        try:
            with opener.open(PING_URL, timeout=timeout_s) as resp:
                resp.read()
        except Exception:
            return uri, None
        latency_ms = (time.monotonic() - t0) * 1000
        return uri, latency_ms

    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.unlink(cfg_path)
        except OSError:
            pass


# ── Batch tester ──────────────────────────────────────────────────────────────

def run_tests(
    configs: list[str],
    workers: int = 50,
    timeout_s: float = 5.0,
    top_n: int = 10,
) -> list[tuple[str, float]]:
    """
    Test all configs in parallel.
    Returns a list of (uri, latency_ms) sorted by latency, up to top_n entries.
    Only includes configs that actually responded.
    """
    results: list[tuple[str, float]] = []

    print(f"[tester] Testing {len(configs)} configs with {workers} workers, {timeout_s}s timeout...")
    t_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_test_one, uri, timeout_s): uri for uri in configs}
        done = 0
        for future in as_completed(futures):
            done += 1
            uri, latency = future.result()
            if latency is not None:
                results.append((uri, latency))
            if done % 100 == 0:
                elapsed = time.monotonic() - t_start
                print(f"[tester] {done}/{len(configs)} tested, {len(results)} alive, {elapsed:.0f}s elapsed")

    elapsed = time.monotonic() - t_start
    results.sort(key=lambda x: x[1])
    print(f"[tester] Done. {len(results)}/{len(configs)} responded in {elapsed:.0f}s. Top {top_n} selected.")
    return results[:top_n]
