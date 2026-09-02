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
BOOKING_URL = "https://www.palacehoteltokyo.com/?tripla_booking_widget_open=search&type=plan"

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)


async def check_availability() -> tuple[bool, str]:
    rooms_data = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="ja-JP",
        )
        page = await context.new_page()

        async def on_response(response):
            if f"/book/hotels/{HOTEL_ID}/rooms" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    rooms_data.append(data)
                    print(f"  [API傍受] {response.url[:80]}")
                except Exception:
                    pass

        page.on("response", on_response)

        url = (
            f"https://concierge.tripla.ai/book/hotels/{HOTEL_ID}/"
            f"?checkin_date={CHECKIN}&checkout_date={CHECKOUT}&number_of_units=1"
        )
        print("  ページ読込中...")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            pass

        await page.wait_for_timeout(5000)
        await browser.close()

    if not rooms_data:
        print("  APIレスポンスを傍受できませんでした")
        return False, "傍受失敗"

    for data in rooms_data:
        data_str = json.dumps(data, ensure_ascii=False)
        print(f"  レスポンス（先頭300文字）: {data_str[:300]}")

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

    return False, "部屋未検出"


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
検出元: {source}
━━━━━━━━━━━━━━━━━━━━━━━━━"""
        send_email(f"【速報】パレスホテル東京 空室あり！ {CHECKIN}", message)
        print("  空室検出 → 通知送信完了")
    else:
        print(f"  満室（{timestamp}）")


if __name__ == "__main__":
    asyncio.run(main())
