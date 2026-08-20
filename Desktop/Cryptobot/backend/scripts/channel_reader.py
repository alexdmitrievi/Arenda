"""One-time reader for a public Telegram channel (telethon).

Usage (inside the tool container, session volume mounted at /session):
  python channel_reader.py request-code +79620546601
  python channel_reader.py sign-in 12345          # or the 2FA password
  python channel_reader.py fetch                  # last N messages + media
"""

import asyncio
import json
import os
import sys

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

SESSION_DIR = os.environ.get("TG_SESSION_DIR", "/session")
SESSION = os.path.join(SESSION_DIR, "tbx_telegram")
STATE = os.path.join(SESSION_DIR, "state.json")
MEDIA_DIR = os.path.join(SESSION_DIR, "media")
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
CHANNEL = "CryptoSizeRU"


async def main() -> None:
    cmd = sys.argv[1]
    proxy = None
    raw_proxy = os.environ.get("TG_PROXY", "")  # "socks5:127.0.0.1:10808"
    if raw_proxy:
        scheme, host, port = raw_proxy.replace("/", "").split(":")
        proxy = (scheme, host, int(port))
    client = TelegramClient(SESSION, API_ID, API_HASH, proxy=proxy)
    await client.connect()
    if os.environ.get("TG_PIN_DC"):
        # ТСПУ blocks the native MTProto DC IPs from the datacenter; the
        # api.telegram.org front stays reachable there. Normally unused.
        client.session.set_dc(2, "149.154.167.220", 443)

    if cmd == "request-code":
        phone = sys.argv[2]
        sent = await client.send_code_request(phone)
        state = {"phone": phone, "phone_code_hash": sent.phone_code_hash}
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f)
        print("CODE_REQUESTED")

    elif cmd == "sign-in":
        secret = sys.argv[2]
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)
        try:
            await client.sign_in(
                state["phone"], secret, phone_code_hash=state["phone_code_hash"]
            )
        except SessionPasswordNeededError:
            print("2FA_REQUIRED")
            await client.disconnect()
            return
        me = await client.get_me()
        print("SIGNED_IN id=%s username=%s" % (me.id, me.username))

    elif cmd == "fetch":
        entity = await client.get_entity(CHANNEL)
        messages = await client.get_messages(entity, limit=50)
        os.makedirs(MEDIA_DIR, exist_ok=True)
        data = []
        for m in reversed(messages):
            item = {"id": m.id, "date": str(m.date), "text": m.text or ""}
            if m.media:
                path = await m.download_media(MEDIA_DIR)
                item["media"] = path
            data.append(item)
        with open(os.path.join(SESSION_DIR, "messages.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print("FETCHED %d" % len(data))

    else:
        print("unknown command")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
