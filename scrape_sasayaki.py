# -*- coding: utf-8 -*-
"""
「ささやき」(https://sasayaki-esthe.com/scheduleAll.html) の出勤データを、
公式サイトから取得するスクリプト。

このサイトは日付の切り替えが「日付をクリックする」形になっているため、
Playwright（実際にブラウザを操作するライブラリ）で日付を順にクリックしながら
1週間分を読み取っている。

・日付（「24 火曜」のような表記）を順にクリックする
・画面に表示されているセラピストのリンク（個人ページ item_○○ へのリンク）から名前を抜き出す
・あわせて、そのリンク先（セラピスト個人ページのURL）も保存する
・結果を data/sasayaki.json に保存する

※ うまく取れなかった日は、原因調査用の情報をログに表示する。
"""
import re
import json
import datetime
import time
import os
from playwright.sync_api import sync_playwright

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間

SHOP_NAME = "ささやき"
REGION = "千葉"
BASE_URL = "https://sasayaki-esthe.com/scheduleAll.html"
SITE_ROOT = "https://sasayaki-esthe.com"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "sasayaki.json")

WEEKDAYS = "月火水木金土日"  # date.weekday() の 0=月 ～ 6=日

# 「名前(25歳)」「名前（25）」から名前部分だけを取り出す
NAME_PATTERN = re.compile(r'^(.+?)\s*[\(（]\d{2}歳?[\)）]')
# 年齢の表記が無い場合に「名前らしい」とみなす文字
NAME_ONLY_PATTERN = re.compile(r'^[ぁ-んァ-ヶー一-龠々\s　]{2,12}$')

# 画面に「表示されている」セラピストのリンク（文字とリンク先）だけを集めるJavaScript
JS_VISIBLE_LINKS = """
els => els
  .filter(e => e.offsetParent !== null)
  .map(e => [e.innerText.trim(), e.getAttribute('href') || ''])
  .filter(x => x[0].length > 0)
"""

# 日付のボタンを探してクリックするJavaScript
# （「日にちの数字」と「曜日」の両方を含む、短い文字のボタンを探す）
JS_CLICK_DATE = """
([day, wd]) => {
  const dayRe = new RegExp('(^|[^0-9])' + day + '([^0-9]|$)');
  const cands = Array.from(document.querySelectorAll('a, li, button'))
    .filter(e => {
      const t = (e.innerText || '').replace(/\\s+/g, ' ').trim();
      return t.length > 0 && t.length <= 16 && dayRe.test(t) && t.includes(wd);
    });
  if (cands.length === 0) return false;
  // 一番内側（文字が短い）のものを選んでクリック
  cands.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
  // 押せる部品（a / button）を選ぶ。li の場合は、中にある a / button を押す
  // （li 自体を押しても、中のリンクの動作は起きないため）
  const c = cands[0];
  const target = (c.matches('a, button') ? c : null) || c.querySelector('a, button') || c.closest('a, button') || c;
  target.click();
  return (target.outerHTML || '').replace(/\\s+/g, ' ').slice(0, 160);
}
"""

# 名前 → 個人ページURL（読み取ったものをここに貯めていく）
PROFILE_URLS = {}


def click_date_tab(page, date_obj):
    """指定日の日付ボタンを探してクリックする"""
    clicked = page.evaluate(JS_CLICK_DATE, [str(date_obj.day), WEEKDAYS[date_obj.weekday()]])
    if clicked:
        print(f"    押したボタン: {clicked}")
        page.wait_for_timeout(500)
    return bool(clicked)


def read_names(page):
    items = page.eval_on_selector_all('a[href*="item_"]', JS_VISIBLE_LINKS)
    names = []
    seen = set()
    for t, href in items:
        first_line = t.split("\n")[0].strip()
        m = NAME_PATTERN.match(first_line) or NAME_PATTERN.match(t)
        if m:
            name = m.group(1).strip()
        elif NAME_ONLY_PATTERN.match(first_line):
            name = first_line.strip()
        else:
            continue
        if name and name not in seen:
            seen.add(name)
            names.append(name)
            if href:
                PROFILE_URLS[name] = SITE_ROOT + href if href.startswith("/") else (
                    href if href.startswith("http") else SITE_ROOT + "/" + href)
    return names


def wait_for_names(page, prev_names):
    """クリックした後、リストが表示され、前日の内容から切り替わるまで最大10秒待つ"""
    names = []
    for _ in range(20):
        names = read_names(page)
        if names and names != prev_names:
            return names
        page.wait_for_timeout(500)
    return names


def debug_page(page):
    """名前が取れなかったときに、原因を探るためにページの様子を表示する"""
    try:
        print(f"    [調査] 表示されたURL: {page.url}")
        print(f"    [調査] ページタイトル: {page.title()}")
        body = page.evaluate("() => document.body ? document.body.innerText : ''")
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        print(f"    [調査] 本文の行数: {len(lines)} / 枠（iframe）の数: {len(page.frames) - 1}")
        for l in lines[:20]:
            print(f"    [調査] 本文: {l[:80]}")
        dates = page.evaluate(
            "() => Array.from(document.querySelectorAll('a, li, button'))"
            ".map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim())"
            ".filter(t => t.length > 0 && t.length <= 16 && /[月火水木金土日]/.test(t) && /[0-9]/.test(t))"
            ".slice(0, 20)"
        )
        links = page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => a.getAttribute('href') + ' | ' + (a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 30))"
            ".filter(t => /item/.test(t)).slice(0, 15)"
        )
        print(f"    [調査] 日付らしいボタン: {dates}")
        print(f"    [調査] セラピストらしいリンク: {links}")
    except Exception as e:
        print(f"    [調査] 失敗: {e}")


def debug_structure(page):
    """毎日同じ人数・同じ名前になったときに、ページの作りを表示する（原因調査用）"""
    try:
        info = page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('a[href*="item_"]'));
            const vis = all.filter(e => e.offsetParent !== null);
            const out = ['セラピストのリンク: 全部で' + all.length + '個 / 画面に表示' + vis.length + '個'];
            const first = vis[0] || all[0];
            if (first) {
                out.push('最初のリンク: ' + first.outerHTML.replace(/\\s+/g, ' ').slice(0, 200));
                let el = first;
                for (let d = 1; d <= 6 && el.parentElement; d++) {
                    el = el.parentElement;
                    const n = el.querySelectorAll('a[href*="item_"]').length;
                    out.push('  ' + d + '段上 <' + el.tagName.toLowerCase() + ' id="' + (el.id || '') + '" class="' + (el.className || '') + '"> 中のリンク' + n + '個');
                }
            }
            return out;
        }""")
        for line in info:
            print(f"    [調査] {line[:300]}")
    except Exception as e:
        print(f"    [調査] 失敗: {e}")


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    week_dates = [(today + datetime.timedelta(days=i)) for i in range(7)]

    schedule_by_date = {}
    all_names = set()
    debug_shown = False

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # お店の許可を得たうえで、アロマモアと同じく普通のブラウザ（Chrome）として名乗る
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ))
        response = page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        print(f"ページの応答: {response.status if response else '不明'}")
        page.wait_for_timeout(2000)

        prev_names = None
        prev_day_names = None
        structure_shown = False
        for date_obj in week_dates:
            date_str = date_obj.isoformat()
            names = []
            try:
                for attempt in range(2):  # 0件なら1回だけ押し直して再挑戦
                    if not click_date_tab(page, date_obj):
                        print(f"[警告] {date_str} の日付ボタンが見つかりませんでした")
                        break
                    names = wait_for_names(page, prev_names)
                    if names:
                        break
                    print(f"  [再試行] {date_str} が0件だったため、押し直します")
            except Exception as e:
                print(f"[警告] {date_str} の取得に失敗しました: {e}")
                names = []

            if not names and not debug_shown:
                debug_page(page)
                debug_shown = True

            if names:
                prev_names = names

            same = bool(names) and names == prev_day_names
            schedule_by_date[date_str] = names
            all_names.update(names)
            print(f"{date_str}: {len(names)}名 出勤確認  例: {'、'.join(names[:5])}"
                  + ("  ※前日とまったく同じ顔ぶれ" if same else ""))
            if same and not structure_shown:
                debug_structure(page)
                structure_shown = True
            prev_day_names = names
            time.sleep(1.0)

        browser.close()

    therapists = [{"name": name, "area": "", "url": PROFILE_URLS.get(name, "")}
                  for name in sorted(all_names)]

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
