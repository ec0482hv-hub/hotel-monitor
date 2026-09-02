#!/usr/bin/env python3
import asyncio
import smtplib
import os
import json
import sys
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
HOTEL_URL = "https://www.palacehoteltokyo.com/"
BOOKING_URL = HOTEL_URL + "?tripla_booking_widget_open=search&type=plan"

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)


def target_found_in(text: str) -> bool:
    return any(variant in text for variant in TARGET_ROOM_VARIANTS)


async def check_availability() -> tuple[bool, str]:
    found = False
    source = ""
    intercepted_json = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = await context.new_page()

        async def on_response(response):
            if "tripla" in response.url and response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        data = await response.json()
                        intercepted_json.append(json.dumps(data, ensure_ascii=False))
                        print(f"  [API] {response.url[:80]}")
                    except Exception:
                        pass

        page.on("response", on_response)

        print(f"  ページ読込中...")
        await page.goto(BOOKING_URL, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(4000)

        try:
            checkin_input = await page.query_selector(
                "input[data-testid='checkin'], input[placeholder*='チェックイン'], "
                "input[placeholder*='Check-in'], input[name='checkin_date']"
            )
            if checkin_input:
                await checkin_input.fill(CHECKIN)
                await page.wait_for_timeout(1000)

            checkout_input = await page.query_selector(
                "input[data-testid='checkout'], input[placeholder*='チェックアウト'], "
                "input[placeholder*='Check-out'], input[name='checkout_date']"
            )
            if checkout_input:
                await checkout_input.fill(CHECKOUT)
                await page.wait_for_timeout(1000)

            search_btn = await page.query_selector(
                "button[data-testid='search'], button:has-text('検索'), "
                "button:has-text('Search'), button:has-text('空室確認')"
            )
            if search_btn:
                await search_btn.click()
                await page.wait_for_timeout(5000)
        except Exception as e:
            print(f"  [警告] ウィジェット操作: {e}")

        await page.wait_for_timeout(3000)
        try:
            page_text = await page.inner_text("body")
            if target_found_in(page_text):
                found = True
                source = "ページテキスト"
        except Exception as e:
            print(f"  [警告] テキスト取得: {e}")

        for json_str in intercepted_json:
            if target_found_in(json_str):
                found = True
                source = "APIレスポンス"
                break

        await browser.close()

    return found, source


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

今すぐ予約ページを開いてください：
{BOOKING_URL}

検出時刻: {timestamp}
━━━━━━━━━━━━━━━━━━━━━━━━━"""
        send_email(f"【速報】パレスホテル東京 空室あり！ {CHECKIN}", message)
        print("  空室検出 → 通知送信完了")
    else:
        print(f"  満室（{timestamp}）")


if __name__ == "__main__":
    asyncio.run(main())
