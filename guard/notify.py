"""Send alerts to Telegram (text + chart) and WhatsApp via CallMeBot (text)."""
import os
import urllib.parse

import requests

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
WA_PHONE = os.getenv("WHATSAPP_PHONE", "")
WA_KEY = os.getenv("WHATSAPP_APIKEY", "")


def telegram(text: str, photo: str | None = None) -> bool:
    if not (TG_TOKEN and TG_CHAT):
        return False
    base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if photo and os.path.exists(photo) and len(text) <= 1000:
            with open(photo, "rb") as f:
                r = requests.post(f"{base}/sendPhoto", data={"chat_id": TG_CHAT, "caption": text},
                                  files={"photo": f}, timeout=30)
        else:
            r = requests.post(f"{base}/sendMessage",
                              data={"chat_id": TG_CHAT, "text": text[:4000]}, timeout=30)
            if photo and os.path.exists(photo):
                with open(photo, "rb") as f:
                    requests.post(f"{base}/sendPhoto", data={"chat_id": TG_CHAT},
                                  files={"photo": f}, timeout=30)
        return r.ok
    except requests.RequestException as e:
        print("telegram error:", e)
        return False


def whatsapp(text: str) -> bool:
    if not (WA_PHONE and WA_KEY):
        return False
    url = ("https://api.callmebot.com/whatsapp.php?phone=" + urllib.parse.quote(WA_PHONE)
           + "&apikey=" + urllib.parse.quote(WA_KEY) + "&text=" + urllib.parse.quote(text[:1500]))
    try:
        return requests.get(url, timeout=40).ok
    except requests.RequestException as e:
        print("whatsapp error:", e)
        return False


def configured() -> bool:
    return bool((TG_TOKEN and TG_CHAT) or (WA_PHONE and WA_KEY))


def send(text: str, short: str | None = None, photo: str | None = None) -> bool:
    """Returns True only if at least one channel actually delivered it."""
    print("\n" + text + "\n")
    ok_tg = telegram(text, photo)
    ok_wa = whatsapp(short or text)
    return ok_tg or ok_wa


def telegram_commands(offset: int):
    """Read messages you sent the bot (e.g. 'status'). Returns (commands, new_offset)."""
    if not (TG_TOKEN and TG_CHAT):
        return [], offset
    try:
        r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                         params={"offset": offset, "timeout": 0}, timeout=20).json()
    except (requests.RequestException, ValueError):
        return [], offset
    cmds = []
    for u in r.get("result", []):
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) == str(TG_CHAT):
            cmds.append((msg.get("text") or "").strip().lower())
    return cmds, offset
