# -*- coding: utf-8 -*-
"""
「アロマモア」の出勤データを、掲載サイト「メンズエステマニアックス」経由で取得するスクリプト。
(店舗公式サイト aromamore.tokyo は自動アクセスを禁止していたため、
 自動アクセスが許可されているこちらの掲載ページを利用しています)

・当日は https://www.es-maniax.com/shop/t291962/s_shift/
・翌日以降は末尾に /DayAfter-1/ 〜 /DayAfter-6/ を付けたURLで1週間分を巡回する
・各ページから「セラピスト名(年齢)」の形の文字列を抜き出す
・結果を data/aromamore.json に保存する

※ 注意：ページの見た目をもとに作成しています。サイト側の構造が変わると
  動かなくなることがあります。初回実行時に0件だったり、名前が
  おかしい形で取れる場合は、その旨教えてください。
"""
import requests
from bs4 import BeautifulSoup
import re
import json
import datetime
import time
import os

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間

SHOP_NAME = "アロマモア"
REGION = "東京"
BASE_URL = "https://www.es-maniax.com/shop/t291962/s_shift/"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "aromamore.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# 「名前(年齢)」の形の文字列を拾う正規表現（名前と括弧の間に空白が入る場合にも対応）
NAME_PATTERN = re.compile(r'([ぁ-んァ-ヶ一-龠ー]{2,12})\s*[\(（](\d{2})[\)）]')


def get_week_dates():
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    return [(today + datetime.timedelta(days=i)).isoformat() for i in range(7)]


def fetch_day(offset):
    """指定日(0=今日, 1=明日...)の出勤者名リストを返す"""
    url = BASE_URL if offset == 0 else f"{BASE_URL}DayAfter-{offset}/"
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()

    # デバッグ用：取得できた内容のサイズと、期待する文言が含まれているか確認
    print(f"  status={res.status_code} bytes={len(res.text)} "
          f"contains_shop_name={'アロマモア' in res.text} "
          f"contains_schedule_word={'出勤スケジュール' in res.text}")

    soup = BeautifulSoup(res.text, "html.parser")

    # スケジュール一覧が含まれるメインエリアのテキストから名前を抽出
    text = soup.get_text(" ", strip=True)
    names = NAME_PATTERN.findall(text)

    seen = set()
    result = []
    for name, age in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    week_dates = get_week_dates()

    schedule_by_date = {}
    all_names = set()

    for offset, date_str in enumerate(week_dates):
        try:
            names = fetch_day(offset)
        except Exception as e:
            print(f"[警告] {date_str} の取得に失敗しました: {e}")
            names = []

        schedule_by_date[date_str] = names
        all_names.update(names)
        print(f"{date_str}: {len(names)}名 出勤確認")
        time.sleep(1.5)

    therapists = [{"name": name, "area": "新宿/東新宿/高田馬場/恵比寿/銀座/日本橋"} for name in sorted(all_names)]

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
