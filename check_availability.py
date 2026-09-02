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
                    print(f"  [先頭300] {data_str[:300]}")
                except Exception as e:
                    print(f"  [傍受エラー] {e}")

        page.on("response", on_response)

        print("  ページ読込中...")
        try:
            await page.goto(BOOKING_URL, wait_until="networkidle", timeout=45000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        # bw.tripla.ai のiframeを取得
        tripla_frame = None
        for frame in page.frames:
            if "bw.tripla.ai" in frame.url:
                tripla_frame = frame
                print(f"  [triplaフレーム] {frame.url[:120]}")
                break

        if tripla_frame is None:
            print("  triplaフレームが見つかりません")
            for frame in page.frames:
                print(f"  [フレーム] {frame.url[:80]}")
        else:
            # iframeのHTML先頭を確認
            try:
                iframe_html = await tripla_frame.content()
                print(f"  [iframeHTML先頭1000] {iframe_html[:1000]}")
            except Exception as e:
                print(f"  HTML取得失敗: {e}")

            # 「部屋」タブをクリック
            try:
                await tripla_frame.click("text=部屋", timeout=5000)
                print("  「部屋」タブをクリック成功")
                await page.wait_for_timeout(4000)
            except Exception as e:
                print(f"  「部屋」タブクリック失敗: {e}")
                # 別の方法でクリック
                try:
                    tabs = await tripla_frame.query_selector_all("[role='tab'], button")
                    for tab in tabs:
                        text = await tab.inner_text()
                        if "部屋" in text or "Room" in text:
                            await tab.click()
                            print(f"  部屋タブクリック（テキスト={text.strip()}）")
                            await page.wait_for_timeout(4000)
                            break
                except Exception as e2:
                    print(f"  部屋タブ代替クリック失敗: {e2}")

        # スクリーンショット
        await page.screenshot(path="debug_screenshot.png", full_page=True)
        print("  スクリーンショット保存")

        await page.wait_for_timeout(2000)

        print(f"  傍受API数: {len(all_rooms_data)}")
        has_dated = any(CHECKIN in d["url"] for d in all_rooms_data)
        print(f"  日付付きAPI: {has_dated}")

        await browser.close()

    # 解析
    for item in sorted(all_rooms_data, key=lambda d: (CHECKIN in d["url"]), reverse=True):
        data = item["data"]
        data_str = json.dumps(data, ensure_ascii=False)
        if not any(v in data_str for v in TARGET_ROOM_VARIANTS):
            continue
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

    print("  対象部屋未検出")
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
