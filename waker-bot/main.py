import os
import json
import httpx
from flask import Flask, request

# ── Konfigurasi dari Environment ──
BOT_TOKEN = os.environ["BOT_TOKEN"]
GH_PAT = os.environ["GH_PAT"]
CODESPACE_NAME = os.environ.get("CODESPACE_NAME", "ideal-space-telegram-pvq67749v56h677r")
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "").split(",")

# ── Telegram API ──
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# ── GitHub API ──
GH_HEADERS = {
    "Authorization": f"Bearer {GH_PAT}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "HermesWakerBot/1.0",
}


def tg_send(chat_id, text):
    """Kirim pesan via Telegram API."""
    try:
        httpx.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception:
        pass


def codespace_state():
    """Cek status codespace."""
    try:
        r = httpx.get(
            f"https://api.github.com/user/codespaces/{CODESPACE_NAME}",
            headers=GH_HEADERS, timeout=10,
        )
        return r.json().get("state", "unknown") if r.status_code == 200 else None
    except Exception:
        return None


def codespace_start():
    """Start codespace."""
    try:
        r = httpx.post(
            f"https://api.github.com/user/codespaces/{CODESPACE_NAME}/start",
            headers=GH_HEADERS, timeout=30,
        )
        return r.status_code in (200, 202)
    except Exception:
        return False


def codespace_stop():
    """Stop codespace."""
    try:
        r = httpx.post(
            f"https://api.github.com/user/codespaces/{CODESPACE_NAME}/stop",
            headers=GH_HEADERS, timeout=30,
        )
        return r.status_code in (200, 202)
    except Exception:
        return False


# ── Route: Health Check ──
@app.route("/health")
def health():
    return "alive", 200


# ── Route: Telegram Webhook ──
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data:
        return "ok", 200

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    user_id = str(msg["from"]["id"])
    text = msg.get("text", "").strip().lower()

    # Validasi user
    if user_id not in ALLOWED_USERS:
        tg_send(chat_id, "❌ Kamu tidak diizinkan menggunakan bot ini.")
        return "ok", 200

    if text == "/start":
        tg_send(chat_id,
            "🤖 *Hermes Waker Bot*\n\n"
            "Perintah:\n"
            "`/wake` — Bangunin codespace\n"
            "`/status` — Cek status codespace\n"
            "`/sleep` — Matiin codespace")

    elif text == "/status":
        state = codespace_state()
        if state:
            tg_send(chat_id,
                f"📊 *Status Codespace*\n"
                f"State: `{state}`\n"
                f"Nama: `{CODESPACE_NAME}`")
        else:
            tg_send(chat_id, "❌ Gagal cek status codespace.")

    elif text == "/wake":
        state = codespace_state()
        if state == "Running":
            tg_send(chat_id, "✅ Codespace **sudah running**.")
        elif state == "Starting":
            tg_send(chat_id, "⏳ Codespace **sedang start**...")
        else:
            tg_send(chat_id, "⏳ Menyalakan codespace...")
            if codespace_start():
                tg_send(chat_id,
                    "✅ Codespace *starting*! Tunggu ~30-60 detik.\n"
                    "Gunakan `/status` untuk cek progress.")
            else:
                tg_send(chat_id, "❌ Gagal start codespace.")

    elif text == "/sleep":
        tg_send(chat_id, "⏳ Mematikan codespace...")
        if codespace_stop():
            tg_send(chat_id, "✅ Codespace dimatikan.")
        else:
            tg_send(chat_id, "❌ Gagal stop codespace.")

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
