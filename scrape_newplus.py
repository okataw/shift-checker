# -*- coding: utf-8 -*-
"""
「NEW+PLUS」(https://o-plus.site/schedule.html) の出勤データを取得するスクリプト。

このサイトは出勤者の一覧がJavaScriptで後から画面に描き込まれるタイプのため、
requestsで直接ページを読んでも中身が空になってしまう。
そのため Playwright（実際にブラウザを操作するライブラリ）を使い、
ページが完成した状態を待ってから読み取っている。

・schedule.html?0 〜 schedule.html?6 で7日分（今日から1週間）を巡回する
  （?なし = 今日、?1 = 明日 ... という形になっている）
・各ページの中から、プロフィールへのリンク(profile.html?ID)の近くにある
  名前らしき文字列（"○○(年齢)" の形）を抜き出す
・結果を data/newplus.json に保存する

※ 注意：JavaScriptで描画される中身の細かい構造は、実際にブラウザで
  レンダリングしてみないと確認できませんでした。初回実行時に
  0件だったり、名前がおかしい形で取れる場合は、その旨教えてください。
  抜き出し方（セレクタ）の調整が必要になります。
"""
import json
import re
import datetime
import time
import os
from playwright.sync_api import sync_playwright

SHOP_NAME = "NEW+PLUS"
REGION = "東京"
BASE_URL = "https://o-plus.site/schedule.html"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "newplus.json")

# 名前っぽい文字列を拾うための正規表現: 「漢字/ひらがな/カタカナの名前(数字)」
NAME_PATTERN = re.compile(r'([ぁ-んァ-ヶ一-龠ー]{2,10})\((\d{2})\)')


def fetch_day(page, offset):
    """指定日(0=今日, 1=明日...)の出勤者一覧を取得して名前のリストを返す"""
    url = BASE_URL if offset == 0 else f"{BASE_URL}?{offset}"
    page.goto(url, wait_until="networkidle", timeout=30000)
    # JavaScriptでの描画が完了するまで少し待つ
    page.wait_for_timeout(1500)

    body_text = page.inner_text("body")
    names = NAME_PATTERN.findall(body_text)
    # 重複を除きつつ順序を保持
    seen = set()
    result = []
    for name, age in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    today = datetime.date.today()
    week_dates = [(today + datetime.timedelta(days=i)).isoformat() for i in range(7)]

    schedule_by_date = {}
    all_names = set()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ))

        for offset, date_str in enumerate(week_dates):
            try:
                names = fetch_day(page, offset)
            except Exception as e:
                print(f"[警告] {date_str} の取得に失敗しました: {e}")
                names = []

            schedule_by_date[date_str] = names
            all_names.update(names)
            print(f"{date_str}: {len(names)}名 出勤確認")
            time.sleep(1.0)

        browser.close()

    therapists = [{"name": name, "area": "秋葉原/新橋/恵比寿/北千住"} for name in sorted(all_names)]

    output = {
        "shop": SHOP_NAME,
        "region": REGION,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "dates": week_dates,
        "therapists": therapists,
        "schedule": schedule_by_date,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"保存しました: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
