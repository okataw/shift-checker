# -*- coding: utf-8 -*-
"""
「アロマモア」(https://aromamore.tokyo/scheduleAll.html) の出勤データを、
公式サイトから取得するスクリプト。

このサイトは日付の切り替えが「タブをクリックする」形になっているため、
Playwright（実際にブラウザを操作するライブラリ）でタブを順にクリックしながら
1週間分を読み取っている。

・日付タブ（「9 26 土」のような表記）を順にクリックする
・画面に表示されているセラピストのリンク（「名前(25歳)」の形）から名前を抜き出す
・結果を data/aromamore.json に保存する

※ 注意：ページの見た目をもとに作成しています。サイト側の構造が変わると
  動かなくなることがあります。0件だったり、名前がおかしい形で取れる場合は教えてください。
"""
import re
import json
import datetime
import time
import os
from playwright.sync_api import sync_playwright

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間

SHOP_NAME = "アロマモア"
REGION = "東京"
BASE_URL = "https://aromamore.tokyo/scheduleAll.html"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "aromamore.json")

# 「名前(25歳)」から名前部分だけを取り出す
NAME_PATTERN = re.compile(r'^(.+?)\s*[\(（]\d{2}歳?[\)）]')

# 画面に「表示されている」セラピストのリンク文字列だけを集めるJavaScript
# （他の日の分がページ内に隠れて入っている場合でも、選択中の日だけを拾うため）
JS_VISIBLE_NAMES = """
els => els
  .filter(e => e.offsetParent !== null)
  .map(e => e.innerText.trim())
  .filter(t => t.length > 0)
"""


def click_date_tab(page, date_obj):
    """指定日の日付タブを探してクリックする"""
    target = f"{date_obj.month} {date_obj.day} "
    tabs = page.locator('a[href="javascript:void(0);"]')
    for i in range(tabs.count()):
        text = re.sub(r"\s+", " ", tabs.nth(i).inner_text()).strip() + " "
        if text.startswith(target):
            # 画面上部の固定メニューなどがタブに重なってクリックが遮られることがあるため、
            # 画面上の位置に関係なく、タブ自体に直接クリック命令を送る
            tabs.nth(i).evaluate("e => e.click()")
            page.wait_for_timeout(1500)
            return True
    return False


def read_names(page):
    texts = page.eval_on_selector_all('a[href^="/item_"]', JS_VISIBLE_NAMES)
    names = []
    seen = set()
    for t in texts:
        m = NAME_PATTERN.match(t)
        if not m:
            continue
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


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
        page.wait_for_timeout(2000)

        for date_obj in week_dates:
            date_str = date_obj.isoformat()
            try:
                if not click_date_tab(page, date_obj):
                    print(f"[警告] {date_str} の日付タブが見つかりませんでした")
                    names = []
                else:
                    names = read_names(page)
            except Exception as e:
                print(f"[警告] {date_str} の取得に失敗しました: {e}")
                names = []

            schedule_by_date[date_str] = names
            all_names.update(names)
            print(f"{date_str}: {len(names)}名 出勤確認")
            time.sleep(1.0)

        browser.close()

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
