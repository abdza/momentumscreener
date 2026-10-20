#!/bin/bash
# Run a headless Claude "ticker analysis" and send the result to the screener Telegram chat.
# Intended for cron, e.g. (Malaysia time, 00:30 = 12:30 ET during EDT):
#   30 0 * * 2-6 /home/abdza/momentumscreener/ticker_analysis.sh

cd /home/abdza/momentumscreener
source secrets.env

# 1 = send the result to Telegram, 0 = only write it to the log
SEND_TELEGRAM=1

LOG_FILE=ticker_analysis_cron.log
OUT_FILE=$(mktemp)
trap 'rm -f "$OUT_FILE"' EXIT

# Don't let two runs overlap
exec 9>/tmp/ticker_analysis.lock
flock -n 9 || { echo "$(date) already running, skipping" >> "$LOG_FILE"; exit 0; }

PROMPT='Do a ticker analysis. Follow the ticker analysis workflow in memory: analyze all of today'"'"'s data from scratch, pick one top ticker, and append the entry to ticker_analysis_log.md. Your final reply is sent to Telegram as plain text, so write every ticker symbol with a leading dollar sign (e.g. $ABCD) so it can be linked to TradingView, and make it only the pick summary: top pick with price, entry / stop / target, a few short rationale bullets, and runners-up. No markdown tables, no preamble, under 3000 characters.'

echo "$(date) starting ticker analysis" >> "$LOG_FILE"

timeout 20m /home/abdza/.local/bin/claude -p "$PROMPT" \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Glob" "Grep" "Edit" "Write" \
        "Bash(python:*)" "Bash(python3:*)" "Bash(venv/bin/python:*)" \
        "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Bash(tail:*)" "Bash(grep:*)" \
        "Bash(find:*)" "Bash(wc:*)" "Bash(date:*)" "Bash(TZ=*)" \
    > "$OUT_FILE" 2>> "$LOG_FILE"
STATUS=$?

if [ $STATUS -ne 0 ] || [ ! -s "$OUT_FILE" ]; then
    echo "⚠️ Ticker analysis failed (exit $STATUS). See $PWD/$LOG_FILE" > "$OUT_FILE"
fi
cat "$OUT_FILE" >> "$LOG_FILE"

if [ "$SEND_TELEGRAM" != 1 ]; then
    echo "$(date) done (claude exit $STATUS, Telegram off)" >> "$LOG_FILE"
    exit 0
fi

# Send as HTML (ticker symbols like $ABCD link to TradingView), split into chunks under Telegram's 4096-char limit
python3 - "$OUT_FILE" <<'EOF'
import os, re, sys, json, html, urllib.request, urllib.parse

text = "🎯 Ticker Analysis\n\n" + open(sys.argv[1]).read().strip()
url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"

chunks, cur = [], ""
for line in text.splitlines(keepends=True):
    while len(line) > 4000:
        chunks.append(line[:4000]); line = line[4000:]
    if len(cur) + len(line) > 4000:
        chunks.append(cur); cur = ""
    cur += line
if cur.strip():
    chunks.append(cur)

def linkify(chunk):
    chunk = html.escape(chunk, quote=False)
    return re.sub(
        r"\$([A-Z]{1,5}(?:[.-][A-Z])?)\b",
        lambda m: f'<a href="https://www.tradingview.com/chart/?symbol={m.group(1).replace("-", ".")}">{m.group(1)}</a>',
        chunk)

for chunk in chunks:
    data = urllib.parse.urlencode({
        "chat_id": os.environ["TELEGRAM_CHAT_ID"],
        "text": linkify(chunk),
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    resp = json.load(urllib.request.urlopen(url, data, timeout=30))
    if not resp.get("ok"):
        print(f"Telegram error: {resp}", file=sys.stderr)
EOF

echo "$(date) done (claude exit $STATUS)" >> "$LOG_FILE"
