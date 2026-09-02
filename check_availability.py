#!/usr/bin/env python3
import asyncio
import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.async_api import async_playwright
from datetime import datetime

TARGET_ROOM_VARIANTS = [
    "クラブグランドデラックスキング with バルコニー",
    "クラブ グランドデラックスキング with バルコニー",
    "Club Grand Deluxe King with Balcony",
]
CHECKIN = "2026-10-24"
CHECKOUT = "2026-10-25"
HOTEL_ID = "1917"
WIDGET_URL = "https://www.palacehoteltokyo.com/?tripla_booking_widget_open=search&type=plan"
BOOKING_URL = WIDGET_URL

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)


async def check_availability() -> tuple[bool, str]:
    all_rooms_data = []
    intercepted_rooms_url = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="ja-JP",
        )
        page = await context.new_page()

        # rooms APIのURLとレスポンスを傍受
        async def on_response(response):
            nonlocal intercepted_rooms_url
            if "/rooms" in response.url and "tripla" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    all_rooms_data.append(data)
                    intercepted_rooms_url = response.url.split("?")[0]
                    print(f"  [API傍受] {response.url[:80]}")
                except Exception:
                    pass

        page.on("response", on_response)

        # ホテルのウィジェットを開く（セッション確立）
        print("  ウィジェット読込中...")
        try:
            await page.goto(WIDGET_URL, wait_until="networkidle", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(4000)

        # 傍受したURLのベースを使って日付付きでfetch（ブラウザセッション経由）
        if intercepted_rooms_url:
            dated_url = (
                f"{intercepted_rooms_url}"
                f"?order=recommended"
                f"&rooms[][adults]=2"
                f"&checkin_date={CHECKIN}"
                f"&checkout_date={CHECKOUT}"
            )
            print(f"  日付付きAPIを呼び出し中...")
            try:
                result = await page.evaluate(f"""
                    async () => {{
                        const r = await fetch('{dated_url}', {{
                            headers: {{'Accept': 'application/json'}},
                            credentials: 'include'
                        }});
                        return {{status: r.status, text: await r.text()}};
                    }}
                """)
                print(f"  fetch結果: status={result['status']}")
                if result["status"] == 200:
                    data = json.loads(result["text"])
                    all_rooms_data.append(data)
                    print(f"  レスポンス（先頭300文字）: {json.dumps(data, ensure_ascii=False)[:300]}")
            except Exception as e:
                print(f"  fetch失敗: {e}")
        else:
            print("  rooms URLを傍受できませんでした")

        await browser.close()

    # 取得したデータを解析（最後のものが最新）
    for data in reversed(all_rooms_data):
        data_str = json.dumps(data, ensure_ascii=False)
        if not any(v in data_str for v in TARGET_ROOM_VARIANTS):
            continue
        rooms = data if isinstance(data, list) else data.get("rooms", data.get("room_types", []))
        for room in (rooms if isinstance(rooms, list) else []):
            room_str = json.dumps(room, ensure_ascii=False)
            if not any(v in room_str for v in TARGET_ROOM_VARIANTS):
                continue
            sold_out = room.get("sold_out", room.get("is_sold_out", False))
            available = room.get("available", room.get("is_available", True))
            print(f"  対象部屋: sold_out={sold_out}, available={available}")
            if sold_out or available is False:
                return False, "満室"
            return True, "APIレスポンス"

    print("  満室または対象部屋未検出")
    return False, ""


def send_email(subject: str, body: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_USER
    msg["To"] = NOTIFY_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print(f"  メール送信完了 → {NOTIFY_EMAIL}")


async def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] 空室チェック開始")

    if os.environ.get("TEST_MODE") == "1":
        found, source = True, "テストモード"
    else:
        found, source = await check_availability()

    if found:
        message = f"""━━━━━━━━━━━━━━━━━━━━━━━━━
【空室発見！】パレスホテル東京
━━━━━━━━━━━━━━━━━━━━━━━━━

部屋: クラブグランドデラックスキング with バルコニー
チェックイン:  {CHECKIN}
チェックアウト: {CHECKOUT}

今すぐ予約ページを開いてください！
{BOOKING_URL}

検出時刻: {timestamp}
━━━━━━━━━━━━━━━━━━━━━━━━━"""
        send_email(f"【速報】パレスホテル東京 空室あり！ {CHECKIN}", message)
        print("  空室検出 → 通知送信完了")
    else:
        print(f"  満室（{timestamp}）")


if __name__ == "__main__":
    asyncio.run(main())
