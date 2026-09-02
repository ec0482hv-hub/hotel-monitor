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
BOOKING_URL = (
    "https://www.palacehoteltokyo.com/"
    "?tripla_booking_widget_open=search&type=plan"
    f"&checkin_date={CHECKIN}&checkout_date={CHECKOUT}"
)

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)


async def check_availability() -> tuple[bool, str]:
    all_rooms_data = []

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
                    all_rooms_data.append({"url": response.url, "data": data})
                    data_str = json.dumps(data, ensure_ascii=False)
                    print(f"  [API傍受] {response.url[:100]}")
                    print(f"  [データ先頭500] {data_str[:500]}")
                except Exception as e:
                    print(f"  [傍受エラー] {e}")

        page.on("response", on_response)

        print("  ページ読込中...")
        try:
            await page.goto(BOOKING_URL, wait_until="networkidle", timeout=45000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        # スクリーンショット保存（UI確認用）
        await page.screenshot(path="debug_screenshot.png", full_page=True)
        print("  スクリーンショット保存")

        # フレーム情報
        for i, frame in enumerate(page.frames):
            print(f"  [frame{i}] {frame.url[:80]}")

        # triplaフレームのHTML確認
        for frame in page.frames:
            if "tripla" in frame.url or "concierge" in frame.url:
                try:
                    html = await frame.content()
                    print(f"  [triplaHTML先頭800] {html[:800]}")
                except Exception as e:
                    print(f"  [HTML取得失敗] {e}")

        # ページ全体のHTMLも確認
        main_html = await page.content()
        print(f"  [メインHTML先頭500] {main_html[:500]}")

        await page.wait_for_timeout(2000)

        # 日付付きAPIが来ているか確認
        has_dated = any(CHECKIN in d["url"] for d in all_rooms_data)
        print(f"  日付付きAPI傍受: {has_dated}")

        await browser.close()

    # データ解析
    for item in all_rooms_data:
        data = item["data"]
        data_str = json.dumps(data, ensure_ascii=False)
        if any(v in data_str for v in TARGET_ROOM_VARIANTS):
            rooms = data if isinstance(data, list) else data.get("rooms", data.get("room_types", []))
            for room in (rooms if isinstance(rooms, list) else []):
                room_str = json.dumps(room, ensure_ascii=False)
                if not any(v in room_str for v in TARGET_ROOM_VARIANTS):
                    continue
                sold_out = room.get("sold_out", room.get("is_sold_out", None))
                available = room.get("available", room.get("is_available", None))
                has_date = CHECKIN in item["url"]
                print(f"  [対象部屋] date={has_date}, sold_out={sold_out}, available={available}")
                if has_date:
                    if sold_out or available is False:
                        return False, "満室"
                    return True, "空室"

    print("  対象部屋未検出（デバッグ情報を確認してください）")
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
https://www.palacehoteltokyo.com/?tripla_booking_widget_open=search&type=plan

検出時刻: {timestamp}
━━━━━━━━━━━━━━━━━━━━━━━━━"""
        send_email(f"【速報】パレスホテル東京 空室あり！ {CHECKIN}", message)
    else:
        print(f"  満室（{timestamp}）")


if __name__ == "__main__":
    asyncio.run(main())
