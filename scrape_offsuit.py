# -*- coding: utf-8 -*-
"""
「Offsuit」(https://offsuit.site/schedule) の出勤データを取得するスクリプト。

このサイトも出勤者一覧がJavaScriptで後から描き込まれるタイプで、
かつ日付の切り替えも「タブをクリックする」形になっているため、
Playwrightで実際にタブをクリックしながら1週間分を読み取っている。

・ページ上部の日付タブ（「8月12日 (水)」のような表記）を順にクリックする
・各日の一覧から「名前(年齢)」の形の文字列を抜き出す
・結果を data/offsuit.json に保存する

※ 注意：一覧の中には「エリアNo.1集客力」のような宣伝用の枠が
  実名と同じ「文字列(年齢)」の形式で混ざっていることがあり、
  完全には除外できていません。明らかにおかしな項目が出た場合は
  教えてください（EXCLUDE_NAMES に追加して除外します）。
"""
import json
import re
import datetime
import time
import os

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間
from playwright.sync_api import sync_playwright

SHOP_NAME = "Offsuit"
REGION = "埼玉"
BASE_URL = "https://offsuit.site/schedule"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "offsuit.json")

# 名前ではない宣伝用の文言（見つかったら随時ここに追加していく）
EXCLUDE_NAMES = {"エリアNo", "新人割"}

NAME_PATTERN = re.compile(r'([ぁ-んァ-ヶ一-龠ー]{2,12}(?:\s[ぁ-んァ-ヶ一-龠ー]{1,12})?)\s*[\(（](\d{2})歳?[\)）]')

WEEKDAY_KANJI = ["日", "月", "火", "水", "木", "金", "土"]


def fetch_day(page, date_obj, is_first):
    """指定日のタブをクリックして、出勤者名リストを返す"""
    # 曜日の表記ゆれ（空白の有無など）に影響されないよう、日付部分だけで探す
    label = f"{date_obj.month}月{date_obj.day}日"

    if not is_first:
        tab = page.get_by_text(label, exact=False).first
        tab.click()
        page.wait_for_timeout(1500)

    body_text = page.inner_text("body")
    matches = NAME_PATTERN.findall(body_text)

    seen = set()
    result = []
    for name, age in matches:
        name = name.strip()
        if name in EXCLUDE_NAMES or any(ex in name for ex in EXCLUDE_NAMES):
            continue
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    week_dates = [(today + datetime.timedelta(days=i)) for i in range(7)]

    schedule_by_date = {}
    all_names = set()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ))
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        for i, date_obj in enumerate(week_dates):
            date_str = date_obj.isoformat()
            try:
                names = fetch_day(page, date_obj, is_first=(i == 0))
            except Exception as e:
                print(f"[警告] {date_str} の取得に失敗しました: {e}")
                names = []

            schedule_by_date[date_str] = names
            all_names.update(names)
            print(f"{date_str}: {len(names)}名 出勤確認")
            time.sleep(1.0)

        browser.close()

    therapists = [{"name": name, "area": "大宮/浦和/赤羽"} for name in sorted(all_names)]

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
