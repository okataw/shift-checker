# -*- coding: utf-8 -*-
"""
「トキョプラ」(https://tokyopla.com/schedule) の出勤データを取得するスクリプト。

・日付ごとに ?day=YYYY-MM-DD&from=YYYY-MM-DD というURLがあるので、1週間分アクセスして回る
・各ページから「セラピスト名」「ルーム（新宿/八王子/立川）」を抜き出す
・結果を data/tokyopla.json に保存する

※ 注意：このスクリプトはサイトの見た目のHTML構造をもとに作成していますが、
  実際にサイト側でHTMLの作りが変わると動かなくなることがあります。
  初回実行時にエラーが出たり、0件しか取れなかった場合は、その旨を教えてください。
"""
import requests
from bs4 import BeautifulSoup
import re
import json
import datetime
import time
import os

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間

SHOP_NAME = "トキョプラ"
REGION = "多摩"
BASE_URL = "https://tokyopla.com/schedule"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "tokyopla.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

THERAPIST_LINK_PATTERN = re.compile(r'^/therapist/\d+$')
ROOM_CANDIDATES = ["新宿", "八王子", "立川"]


def get_week_dates():
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    return [(today + datetime.timedelta(days=i)).isoformat() for i in range(7)]


def fetch_day(date_str):
    """指定日の出勤者一覧を取得して [{'name':..., 'area':...}, ...] を返す"""
    url = f"{BASE_URL}?day={date_str}&from={date_str}"
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 相対パス・絶対URLどちらでも判定できるようにする
        path = href.replace("https://tokyopla.com", "")
        if not THERAPIST_LINK_PATTERN.match(path):
            continue

        name = a.get_text(strip=True)
        if not name:
            continue
        if name in seen:
            continue
        seen.add(name)

        # 名前を含むブロックの近くからルーム名を探す
        block = a.find_parent("li") or a.find_parent("div") or a.parent
        block_text = block.get_text(" ", strip=True) if block else ""

        area = None
        for candidate in ROOM_CANDIDATES:
            if candidate in block_text:
                area = candidate
                break

        results.append({"name": name, "area": area or "不明"})

    return results


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    week_dates = get_week_dates()

    schedule_by_date = {}
    all_names = {}

    for date_str in week_dates:
        try:
            day_people = fetch_day(date_str)
        except Exception as e:
            print(f"[警告] {date_str} の取得に失敗しました: {e}")
            day_people = []

        schedule_by_date[date_str] = [p["name"] for p in day_people]
        for p in day_people:
            all_names[p["name"]] = p["area"]

        print(f"{date_str}: {len(day_people)}名 出勤確認")
        time.sleep(1.5)

    therapists = [{"name": name, "area": area} for name, area in sorted(all_names.items())]

    output = {
        "shop": SHOP_NAME,
        "region": REGION,
        "updated_at": datetime.datetime.now(JST).isoformat(timespec="seconds"),
        "dates": week_dates,
        "therapists": therapists,
        "schedule": schedule_by_date,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"保存しました: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
