# -*- coding: utf-8 -*-
"""
「LINDA SPA」(https://linda-spa.com/schedule/) の出勤データを取得するスクリプト。

・日付ごとに ?dt=<タイムスタンプ> というURLがあるので、1週間分アクセスして回る
  （タイムスタンプは、その日のUTC 6:00＝日本時間15:00に対応する値になっている）
・各ページから「セラピスト名」「ルーム（中目黒/恵比寿/麻布十番/目黒駅/三軒茶屋）」を抜き出す
・結果を data/lindaspa.json に保存する

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

SHOP_NAME = "LINDA SPA"
REGION = "東京"
BASE_URL = "https://linda-spa.com/schedule/"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "lindaspa.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

CAST_LINK_PATTERN = re.compile(r'^/cast/\d+/?$')
ROOM_CANDIDATES = ["中目黒", "恵比寿", "麻布十番", "目黒駅", "三軒茶屋"]


def get_week_dates():
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    return [(today + datetime.timedelta(days=i)) for i in range(7)]


def date_to_dt_param(date_obj):
    """日付を、このサイトのURLパラメータ形式（その日のUTC6:00のタイムスタンプ）に変換する"""
    return int(datetime.datetime(
        date_obj.year, date_obj.month, date_obj.day, 6, 0, 0, tzinfo=datetime.timezone.utc
    ).timestamp())


def fetch_day(date_obj):
    """指定日の出勤者一覧を取得して [{'name':..., 'area':...}, ...] を返す"""
    dt_param = date_to_dt_param(date_obj)
    url = f"{BASE_URL}?dt={dt_param}"
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    seen_hrefs = set()
    current_room = "不明"

    # ページ内をH2見出し（ルーム名）とキャストへのリンクの出現順にたどる
    for el in soup.find_all(["h2", "a"]):
        if el.name == "h2":
            heading_text = el.get_text(strip=True)
            for candidate in ROOM_CANDIDATES:
                if candidate in heading_text:
                    current_room = candidate
                    break
            continue

        href = el.get("href", "")
        path = href.replace("https://linda-spa.com", "")
        if not CAST_LINK_PATTERN.match(path):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        full_text = el.get_text(strip=True)
        # リンクの文字列は「名前【店舗名】...」という形なので、【の手前までを名前とする
        name = full_text.split("【")[0].strip()
        if not name:
            continue

        results.append({"name": name, "area": current_room})

    return results


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    week_dates = get_week_dates()

    schedule_by_date = {}
    all_names = {}

    for date_obj in week_dates:
        date_str = date_obj.isoformat()
        try:
            day_people = fetch_day(date_obj)
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
        "dates": [d.isoformat() for d in week_dates],
        "therapists": therapists,
        "schedule": schedule_by_date,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"保存しました: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
