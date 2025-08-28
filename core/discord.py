import os, requests
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

def send_discord(msg: str):
    if not WEBHOOK:
        return
    try:
        requests.post(WEBHOOK, json={"content": msg}, timeout=5)
    except Exception:
        pass