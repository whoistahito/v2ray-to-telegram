FROM python:3.13-slim

# ── System deps ───────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        unzip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Install xray-core ─────────────────────────────────────────────────────────
# Always pull the latest release for linux-64
RUN set -eux; \
    XRAY_VERSION=$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest \
        | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": "\(.*\)".*/\1/'); \
    curl -fsSL \
        "https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/Xray-linux-64.zip" \
        -o /tmp/xray.zip; \
    unzip -q /tmp/xray.zip xray -d /usr/local/bin/; \
    chmod +x /usr/local/bin/xray; \
    rm /tmp/xray.zip; \
    xray --version

# ── Install Python deps ───────────────────────────────────────────────────────
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir pyTelegramBotAPI "requests[socks]"

# ── Copy source ───────────────────────────────────────────────────────────────
COPY bot.py tester.py ./
COPY parsers/ ./parsers/


CMD ["python", "-u", "bot.py"]
