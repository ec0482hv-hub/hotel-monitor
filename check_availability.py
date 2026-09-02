#!/usr/bin/env python3
import smtplib
import os
import json
import urllib.request
import urllib.error
import http.cookiejar
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

TARGET_ROOM_VARIANTS = [
    "クラブグランドデラックスキング with バルコニー",
    "クラブ グランドデラックスキング with バルコニー",
    "Club Grand Deluxe King with Balcony",
]
CHECKIN = "2026-10-24"
CHECKOUT = "2026-10-25"
BOOKING_URL = "https://www.palacehoteltokyo.com/?tripla_booking_widget_open=search&type=plan"
HOTEL_ID = "1917"

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://concierge.tripla.ai",
    "Referer": "https://concierge.tripla.ai/",
}


def check_availability() -> tuple[bool, str]:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    # Step1: triplaのセッションページにアクセスしてクッキーを取得
    try:
        warmup_url = f"https://concierge.tripla.ai/book/hotels/{HOTEL_ID}/"
        req0 = urllib.request.Request(warmup_url, headers=BASE_HEADERS)
        opener.open(req0, timeout=15)
        print("  セッション確立完了")
    except Exception as e:
        print(f"  セッション確立スキップ: {e}")

    # Step2: 空室APIにアクセス
    rooms_url = (
        f"https://concierge.tripla.ai/book/hotels/{HOTEL_ID}/rooms"
        f"?order=recommended"
        f"&rooms[][adults]=2"
        f"&checkin_date={CHECKIN}"
        f"&checkout_date={CHECKOUT}"
    )
    print(f"  API確認中...")
    try:
        req = urllib.request.Request(rooms_url, headers=BASE_HEADERS)
        with opener.open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"  APIエラー: {e.code} / {body[:200]}")
        return False, f"APIエラー({e.code})"
    except Exception as e:
        print(f"  接続エラー: {e}")
        return False, "接続エラー"

    data_str = json.dumps(data, ensure_ascii=False)
    print(f"  レスポンス（先頭500文字）: {data_str[:500]}")

    if not any(v in data_str for v in TARGET_ROOM_VARIANTS):
        print("  対象部屋なし（満室のため非表示の可能性）")
        return False, ""

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

    print("  部屋名はAPIに含まれているが詳細不明 → 念のため通知")
    return True, "APIレスポンス（要確認）"


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


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] 空室チェック開始")

    if os.environ.get("TEST_MODE") == "1":
        found, source = True, "テストモード"
    else:
        found, source = check_availability()

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
    main()
