# -*- coding: utf-8 -*-
"""
「LINDA SPA」(https://linda-spa.com/schedule/) の出勤データを取得するスクリプト。

このサイトは、GitHubのサーバーによっては接続がタイムアウトすることがある
（実行のたびに割り当てられるサーバーが変わるため、成功したり失敗したりする）。
そのため、実際のブラウザとして振る舞う Playwright を使い、さらに
「取得できなかった日は、前回取得できたデータをそのまま残す」ようにしている。

・日付ごとに ?dt=<タイムスタンプ> というURLがあるので、1週間分アクセスして回る
  （タイムスタンプは、その日のUTC 6:00＝日本時間15:00に対応する値になっている）
・各ページから「セラピスト名」「ルーム（中目黒/恵比寿/麻布十番/目黒駅/三軒茶屋）」を抜き出す
・結果を data/lindaspa.json に保存する
"""
import re
import json
import datetime
import time
import os
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間

SHOP_NAME = "LINDA SPA"
REGION = "東京"
BASE_URL = "https://linda-spa.com/schedule/"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "lindaspa.json")

CAST_LINK_PATTERN = re.compile(r'^/cast/\d+/?$')
ROOM_CANDIDATES = ["中目黒", "恵比寿", "麻布十番", "目黒駅", "三軒茶屋"]

# 「名前(年齢)」の直前の名前部分だけを取り出す正規表現
NAME_PATTERN = re.compile(r'([ぁ-んァ-ヶ一-龠ー]{2,12})\(\d{2}\)')

# 何日連続で接続できなかったら、残りの日を諦めるか
MAX_CONSECUTIVE_FAILURES = 2


def get_week_dates():
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    return [(today + datetime.timedelta(days=i)) for i in range(7)]


def date_to_dt_param(date_obj):
    """日付を、このサイトのURLパラメータ形式（その日のUTC6:00のタイムスタンプ）に変換する"""
    return int(datetime.datetime(
        date_obj.year, date_obj.month, date_obj.day, 6, 0, 0, tzinfo=datetime.timezone.utc
    ).timestamp())


def load_previous():
    """前回保存したデータを読み込む（なければ空）"""
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def parse_people(html):
    """ページのHTMLから [{'name':..., 'area':...}, ...] を抜き出す"""
    soup = BeautifulSoup(html, "html.parser")

    results = []
    seen_names = set()
    current_room = "不明"

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

        match = NAME_PATTERN.search(el.get_text(strip=True))
        if not match:
            continue
        name = match.group(1)

        # 同じ人が同じ日に複数の時間帯で出勤している場合の重複を防ぐ
        if name in seen_names:
            continue
        seen_names.add(name)

        results.append({"name": name, "area": current_room})

    return results


def fetch_day(page, date_obj):
    """指定日の出勤者一覧を取得する（失敗したら1回だけ再挑戦）"""
    url = f"{BASE_URL}?dt={date_to_dt_param(date_obj)}"
    last_error = None
    for attempt in range(2):
        try:
            # 「通信が完全に落ち着くまで」待つとタイムアウトしやすいため、
            # ページの骨組みが読み込まれた時点で進む
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                page.wait_for_selector('a[href*="/cast/"]', timeout=10000)
            except Exception:
                pass  # 出勤者が0人の日もあり得るので、見つからなくても続ける
            return parse_people(page.content())
        except Exception as e:
            last_error = e
            print(f"  [再試行 {attempt + 1}/2] {str(e).splitlines()[0]}")
            time.sleep(5)
    raise last_error


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    week_dates = get_week_dates()

    previous = load_previous()
    prev_schedule = previous.get("schedule", {})
    prev_areas = {t["name"]: t.get("area", "") for t in previous.get("therapists", [])}

    schedule_by_date = {}
    all_names = {}
    consecutive_failures = 0
    success_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ))

        for date_obj in week_dates:
            date_str = date_obj.isoformat()

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                day_people = None  # 今回は繋がらないと判断して、残りは前回データを使う
            else:
                try:
                    day_people = fetch_day(page, date_obj)
                    consecutive_failures = 0
                    success_count += 1
                except Exception as e:
                    print(f"[警告] {date_str} の取得に失敗しました: {str(e).splitlines()[0]}")
                    consecutive_failures += 1
                    day_people = None

            if day_people is None:
                # 取得できなかった日は、前回のデータを引き継ぐ
                old_names = prev_schedule.get(date_str, [])
                schedule_by_date[date_str] = old_names
                for n in old_names:
                    all_names[n] = prev_areas.get(n, "")
                print(f"{date_str}: 取得できず → 前回のデータ({len(old_names)}名)を引き継ぎ")
            else:
                schedule_by_date[date_str] = [x["name"] for x in day_people]
                for x in day_people:
                    all_names[x["name"]] = x["area"]
                print(f"{date_str}: {len(day_people)}名 出勤確認")

            time.sleep(2)

        browser.close()

    therapists = [{"name": name, "area": area} for name, area in sorted(all_names.items())]

    output = {
        "shop": SHOP_NAME,
        "region": REGION,
        # 1日も取得できなかった場合は、最終更新時刻も前回のままにしておく
        "updated_at": (datetime.datetime.now(JST).isoformat(timespec="seconds")
                       if success_count > 0 else previous.get("updated_at", "")),
        "dates": [d.isoformat() for d in week_dates],
        "therapists": therapists,
        "schedule": schedule_by_date,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"保存しました: {OUTPUT_PATH}（今回取得できた日数: {success_count}/7）")


if __name__ == "__main__":
    main()
