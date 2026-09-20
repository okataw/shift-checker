# -*- coding: utf-8 -*-
"""
「LINDA SPA」の出勤データを、掲載サイト「メンズリラク」経由で取得するスクリプト。

(店舗公式サイト linda-spa.com が、GitHub側からのアクセスをブロックしている
 ようだったため、同じ情報が載っている掲載サイトを利用しています)

・当日は https://menesth.jp/8/shop/26522/schedule/
・翌日以降は末尾に ?date=1 〜 ?date=6 を付けたURLで1週間分を巡回する
・在籍人数が多い日は「2ページ目」に分かれることがあるため、
  ページがある限り(最大5ページまで)続けて読みに行く
・結果を data/lindaspa.json に保存する

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

SHOP_NAME = "LINDA SPA"
REGION = "東京"
SHOP_PATH = "/8/shop/26522"
BASE_URL = f"https://menesth.jp{SHOP_PATH}/schedule/"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "lindaspa.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

CAST_LINK_PATTERN = re.compile(rf'^{re.escape(SHOP_PATH)}/\d+/?$')
MAX_PAGES = 5


def get_week_dates():
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    return [(today + datetime.timedelta(days=i)) for i in range(7)]


def fetch_page(offset, page):
    """指定日・指定ページの出勤者名リストを返す"""
    url = f"{BASE_URL}page{page}/" if page > 1 else BASE_URL
    params = {}
    if offset > 0:
        params["date"] = offset

    res = requests.get(url, headers=HEADERS, params=params, timeout=20)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    names = []
    seen = set()
    for a in soup.find_all("a", href=True):
        path = a["href"].replace("https://menesth.jp", "")
        if not CAST_LINK_PATTERN.match(path):
            continue
        name = a.get_text(strip=True)
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)

    return names


def fetch_day(offset):
    """指定日(0=今日, 1=明日...)の出勤者名リストを、ページをまたいで全部集める"""
    all_names = []
    for page in range(1, MAX_PAGES + 1):
        try:
            names = fetch_page(offset, page)
        except requests.exceptions.HTTPError as e:
            if page > 1 and e.response is not None and e.response.status_code == 404:
                # 2ページ目以降が存在しない(=最後まで読み終えた)だけなので、エラー扱いにしない
                break
            raise  # 1ページ目自体が失敗した場合など、それ以外のエラーはそのまま伝える

        if not names:
            break
        all_names.extend(names)
        if len(names) < 8:
            # このサイトは1ページ十数名程度で区切られる想定のため、
            # 少ない件数のページが来たら「最後のページ」とみなして打ち切る
            break
        time.sleep(1)
    return all_names


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    week_dates = get_week_dates()

    schedule_by_date = {}
    all_names = set()

    for offset, date_obj in enumerate(week_dates):
        date_str = date_obj.isoformat()
        try:
            names = fetch_day(offset)
        except Exception as e:
            print(f"[警告] {date_str} の取得に失敗しました: {e}")
            names = []

        schedule_by_date[date_str] = names
        all_names.update(names)
        print(f"{date_str}: {len(names)}名 出勤確認")
        time.sleep(2)

    therapists = [{"name": name, "area": ""} for name in sorted(all_names)]

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
