"""One-time Telegram account login. Writes only to secrets.json.

    python telegram_login.py

You need api_id + api_hash from https://my.telegram.org -> API development
tools. Those are per-application credentials, not a bot token — they identify
the client, not the account.

What this does:
  1. asks for api_id / api_hash (or reads them from secrets.json if present)
  2. sends a login code to your phone through Telegram itself
  3. exchanges it for a StringSession
  4. writes telegram_api_id / telegram_api_hash / telegram_session into
     secrets.json, leaving every other key untouched

The session string is a full authorisation for the account. It is written to a
file that is already gitignored. Do not copy it anywhere else, do not paste it
into chat, and if it ever leaks, terminate that session from Telegram ->
Settings -> Devices.
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
SECRETS = ROOT / "secrets.json"


def ask(prompt, default=""):
    v = input(f"{prompt}{(' [' + default + ']') if default else ''}: ").strip()
    return v or default


def main():
    try:
        import telegram_user as TU
    except Exception as e:
        print("telethon belum dipasang:  python -m pip install telethon")
        print(e)
        return 1

    cur = {}
    if SECRETS.exists():
        try:
            cur = json.loads(SECRETS.read_text(encoding="utf-8"))
        except Exception:
            print("secrets.json tak boleh dibaca — berhenti, jangan timpa.")
            return 1

    print("── Telegram account login ─────────────────────────────")
    print("api_id / api_hash: https://my.telegram.org -> API development tools")
    api_id = ask("api_id", str(cur.get("telegram_api_id", "") or ""))
    api_hash = ask("api_hash", str(cur.get("telegram_api_hash", "") or ""))
    phone = ask("nombor telefon (format +60…)", str(cur.get("telegram_phone", "") or ""))
    if not (api_id.isdigit() and api_hash and phone):
        print("Tak lengkap — api_id mesti nombor, api_hash dan telefon mesti diisi.")
        return 1

    print("\nMenghantar kod ke Telegram anda…")
    try:
        ss, me = TU.login(
            int(api_id), api_hash, phone,
            code_getter=lambda: ask("kod dari Telegram"),
            password_getter=lambda: ask("kata laluan 2FA (kosong kalau tiada)"),
        )
    except Exception as e:
        print(f"\nGagal: {type(e).__name__}: {e}")
        return 1

    cur["telegram_api_id"] = int(api_id)
    cur["telegram_api_hash"] = api_hash
    cur["telegram_phone"] = phone
    cur["telegram_session"] = ss
    SECRETS.write_text(json.dumps(cur, indent=1, ensure_ascii=False), encoding="utf-8")

    print("\nSelesai.")
    print(f"  akaun   : {me['name']} (@{me['username'] or '-'})  id {me['id']}")
    print(f"  ditulis : {SECRETS.name}  (gitignored)")
    print(f"  sesi    : {len(ss)} aksara")
    print("\nUji:  python -c \"import telegram_user as t, json;"
          " s=json.load(open('secrets.json'));"
          " a=t.TgAccount(s['telegram_api_id'],s['telegram_api_hash'],s['telegram_session']).start();"
          " print(a.status()); print(len(a.dialogs(5)),'chat')\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
