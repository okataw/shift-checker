# -*- coding: utf-8 -*-
"""
「Queendom」(https://omiya-mens-este.net/schedule.html) の出勤データを取得するスクリプト。

・日付ごとに ?dat=YYYY-MM-DD というURLがあるので、1週間分アクセスして回る
・各ページから「セラピスト名(年齢)」の項目と、その下の「ルーム（大宮/川越/赤羽/浦和）」を抜き出す
・ページ内では「全店」「大宮」「川越」…と同じ人が複数回出てくるため、名前で重複を除く
・「Wセラピストえま(0)」のような年齢0の項目は、実在のセラピストではなく
  コースの予約枠と思われるため除外する
・取得できなかった日は、前回取得できたデータをそのまま残す
・結果を data/queendom.json に保存する
"""
import requests
from bs4 import BeautifulSoup
import re
import json
import datetime
import time
import os

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間

SHOP_NAME = "Queendom"
REGION = "埼玉"
BASE_URL = "https://omiya-mens-este.net/schedule.html"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "queendom.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# 「名前(年齢)」だけの項目にマッチさせる
NAME_PATTERN = re.compile(r'^(.+?)\s*[\(（](\d{1,2})[\)）]$')
ROOM_CANDIDATES = ["大宮", "川越", "赤羽", "浦和"]


def get_week_dates():
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    return [(today + datetime.timedelta(days=i)).isoformat() for i in range(7)]


def load_previous():
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fetch_html(url):
    """一時的な通信エラーに備え、最大3回まで再試行する"""
    last_error = None
    for attempt in range(3):
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            return res.text
        except Exception as e:
            last_error = e
            print(f"  [再試行 {attempt + 1}/3] {e}")
            time.sleep(3)
    raise last_error


def fetch_day(date_str):
    """指定日の出勤者一覧を取得して [{'name':..., 'area':...}, ...] を返す"""
    html = fetch_html(f"{BASE_URL}?dat={date_str}")
    soup = BeautifulSoup(html, "html.parser")

    results = []
    seen = set()
    for li in soup.find_all("li"):
        m = NAME_PATTERN.match(li.get_text(strip=True))
        if not m:
            continue
        name, age = m.group(1).strip(), int(m.group(2))
        if age == 0:
            continue  # 「Wセラピスト」などの予約枠は除外
        if name in seen:
            continue
        seen.add(name)

        # 同じ項目グループ（名前・時間・ルーム）の中からルーム名を探す
        area = ""
        parent = li.find_parent("ul") or li.parent
        if parent:
            for sib in parent.find_all("li"):
                t = sib.get_text(strip=True)
                if t in ROOM_CANDIDATES:
                    area = t
                    break

        results.append({"name": name, "area": area})
    return results


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    week_dates = get_week_dates()

    previous = load_previous()
    prev_schedule = previous.get("schedule", {})
    prev_areas = {t["name"]: t.get("area", "") for t in previous.get("therapists", [])}

    schedule_by_date = {}
    all_names = {}
    success_count = 0

    for date_str in week_dates:
        try:
            day_people = fetch_day(date_str)
            success_count += 1
            schedule_by_date[date_str] = [p["name"] for p in day_people]
            for p in day_people:
                all_names[p["name"]] = p["area"]
            print(f"{date_str}: {len(day_people)}名 出勤確認")
        except Exception as e:
            old_names = prev_schedule.get(date_str, [])
            schedule_by_date[date_str] = old_names
            for n in old_names:
                all_names[n] = prev_areas.get(n, "")
            print(f"[警告] {date_str} の取得に失敗しました: {e}")
            print(f"{date_str}: 取得できず → 前回のデータ({len(old_names)}名)を引き継ぎ")
        time.sleep(1.5)

    therapists = [{"name": name, "area": area} for name, area in sorted(all_names.items())]

    output = {
        "shop": SHOP_NAME,
        "region": REGION,
        "updated_at": (datetime.datetime.now(JST).isoformat(timespec="seconds")
                       if success_count > 0 else previous.get("updated_at", "")),
        "dates": week_dates,
        "therapists": therapists,
        "schedule": schedule_by_date,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"保存しました: {OUTPUT_PATH}（今回取得できた日数: {success_count}/7）")


if __name__ == "__main__":
    main()
