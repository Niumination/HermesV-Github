#!/usr/bin/env python3
"""
Hermes Webhook Poller — baca antrian dari Supabase, kirim ke Telegram via stdout.

Dipanggil oleh cron job Hermes setiap 5 menit.
Cara panggil: python3 /workspaces/HermesV-Github/scripts/webhook-poller.py

Env vars yang dibutuhkan di Hermes .env:
  SUPABASE_URL=https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY=eyJ...
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

TABLE = "webhook_queue"
BATCH_SIZE = 3
POLL_LOCK_FILE = "/tmp/hermes-webhook-poller.lock"

# ── Guard: cegah concurrent run ──
if os.path.exists(POLL_LOCK_FILE):
    age = time.time() - os.path.getmtime(POLL_LOCK_FILE)
    if age < 300:  # 5 menit
        print("[poller] Masih jalan dari sebelumnya, skip")
        sys.exit(0)

open(POLL_LOCK_FILE, "w").close()

# ── Cek config ──
if not SUPABASE_URL or not SUPABASE_KEY:
    os.remove(POLL_LOCK_FILE)
    print("ERROR: SUPABASE_URL dan SUPABASE_SERVICE_KEY harus di-set di .env")
    sys.exit(1)

try:
    import httpx
except ImportError:
    os.remove(POLL_LOCK_FILE)
    print("ERROR: httpx tidak terinstall. Jalankan: pip install httpx")
    sys.exit(1)


def main():
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    # Ambil antrian pending, urut dari yang paling lama
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE}",
            headers=headers,
            params={
                "status": "eq.pending",
                "order": "created_at.asc",
                "limit": BATCH_SIZE,
                "select": "id,event_type,repository,payload,created_at",
            },
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        print(f"[poller] Gagal ambil antrian: {e}")
        return False

    if not rows:
        return None  # Tidak ada event

    print(f"[poller] Ditemukan {len(rows)} event pending:")
    print()

    for row in rows:
        event_id = row["id"]
        event_type = row.get("event_type", "unknown")
        repo = row.get("repository", "?")
        created = row.get("created_at", "")
        payload = row.get("payload", {})

        # Mark as processing
        try:
            httpx.patch(
                f"{SUPABASE_URL}/rest/v1/{TABLE}",
                headers=headers,
                params={"id": f"eq.{event_id}"},
                json={"status": "processing"},
                timeout=10,
            )
        except Exception as e:
            print(f"[poller] Gagal update status processing: {e}")

        # ── Output yang akan dikirim ke Telegram ──
        ref = payload.get("ref", "")
        if event_type == "push":
            commits = payload.get("commits", [])
            msg = (
                f"📦 **Push** ke `{repo}`\n"
                f"Branch: `{ref.replace('refs/heads/', '')}`\n"
                f"Commits: {len(commits)}\n"
            )
            if commits:
                for c in commits[:5]:
                    msg += f"• `{c.get('id', '')[:7]}` {c.get('message', '').split(chr(10))[0]}\n"
                if len(commits) > 5:
                    msg += f"… +{len(commits) - 5} lagi\n"

        elif event_type == "pull_request":
            pr = payload.get("pull_request", {})
            action = payload.get("action", "?")
            title = pr.get("title", "") or ""
            url = pr.get("html_url", "")
            msg = (
                f"🔀 **PR {action}** `{repo}`\n"
                f"#{pr.get('number', '?')}: {title}\n"
                f"{url}\n"
            )

        elif event_type == "issues":
            issue = payload.get("issue", {})
            action = payload.get("action", "?")
            title = issue.get("title", "") or ""
            url = issue.get("html_url", "")
            msg = (
                f"🎫 **Issue {action}** `{repo}`\n"
                f"#{issue.get('number', '?')}: {title}\n"
                f"{url}\n"
            )

        else:
            msg = (
                f"📡 **Event GitHub** `{repo}`\n"
                f"Type: {event_type}\n"
            )

        print(msg)
        print()

        # Mark as done
        try:
            httpx.patch(
                f"{SUPABASE_URL}/rest/v1/{TABLE}",
                headers=headers,
                params={"id": f"eq.{event_id}"},
                json={
                    "status": "done",
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=10,
            )
        except Exception as e:
            print(f"[poller] Gagal update status done: {e}")

    return True


if __name__ == "__main__":
    try:
        result = main()
        if result is None:
            print("[poller] Tidak ada event baru.")
        elif result is True:
            print("[poller] ✅ Selesai memproses event.")
        else:
            print("[poller] ❌ Gagal.")
    except Exception as e:
        print(f"[poller] Fatal: {e}")
        sys.exit(1)
    finally:
        if os.path.exists(POLL_LOCK_FILE):
            os.remove(POLL_LOCK_FILE)
