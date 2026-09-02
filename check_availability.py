#!/usr/bin/env python3
import asyncio
import smtplib
import os
from urllib.parse import quote
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
HOTEL_CODE = "ab2594fe2b0209921d24ae0d38041497"

CHECKIN_ENC = quote(CHECKIN.replace("-", "/"))
CHECKOUT_ENC = quote(CHECKOUT.replace("-", "/"))
TRIPLA_URL = (
    f"https://bw.tripla.ai/booking/result"
    f"?code={HOTEL_CODE}"
    f"&checkin={CHECKIN_ENC}"
    f"&checkout={CHECKOUT_ENC}"
    f"&type=room"
    f"&is_day_use=false"
    f"&order=recommended"
    f"&is_including_occupied=false"
)
BOOKING_URL = "https://www.palacehoteltokyo.com/?tripla_booking_widget_open=search&type=plan"

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)


async def check_availability() -> tuple[bool, str]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="ja-JP",
        )
        page = await context.new_page()

        print(f"  triplaを開く（日付: {CHECKIN}、空室のみ表示）")
        try:
            await page.goto(TRIPLA_URL, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print(f"  読込エラー（続行）: {e}")
        await page.wait_for_timeout(5000)

        await page.screenshot(path="debug_screenshot.png", full_page=True)

        try:
            page_text = await page.inner_text("body")
        except Exception as e:
            print(f"  テキスト取得失敗: {e}")
            await browser.close()
            return False, ""

        print(f"  [ページテキスト先頭400] {page_text[:400]}")
        await browser.close()

    # 空室のみ表示で開いているので、対象部屋が表示されていれば空室
    for variant in TARGET_ROOM_VARIANTS:
        if variant in page_text:
            print(f"  → 対象部屋を発見 → 空室")
            return True, "空室"

    print("  → 対象部屋が表示されていない → 満室")
    return False, "満室"


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
    else:
        print(f"  満室（{timestamp}）")


if __name__ == "__main__":
    asyncio.run(main())
