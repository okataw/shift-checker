"""
各店舗ホームページの「セラピスト一覧（在籍一覧）」ページを読み込み、
在籍しているセラピスト名の手がかりとなる文字列を docs/rosters.json に保存する。

アプリ側では、★登録しているのに今週の出勤表に載っていない人について、
この一覧に名前が無ければ「退店済」と赤字で表示する。

安全装置:
  ・今週の出勤表に載っている人の 80% 以上が一覧で見つかった店舗だけ
    「判定する（ok: true）」にする。読み込みに失敗した店舗は判定しない。
  ・読み込みに失敗した店舗は、前回成功したときのデータをそのまま使う。
"""
import datetime
import glob
import json
import os
import re
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

JST = datetime.timezone(datetime.timedelta(hours=9))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(BASE_DIR, "docs", "rosters.json")

# 店舗名（出勤表と同じ表記） → セラピスト一覧ページのURL
ROSTER_URLS = {
    "エステの気分": "https://estheno-kibun.com/cast/",
    "ウサじょ学園": "https://usajyo-gakuen.com/cast/",
    "アロマモア": "https://aromamore.tokyo/itemList.html",
    "トキョプラ": "https://tokyopla.com/therapist",
    "Tigger": "https://tigger-esthe.com/therapist",
    "アマテラス横浜": "https://amaterasu-yokohama.com/therapist",
    "LINDA SPA": "https://linda-spa.com/cast/",
    "NEW+PLUS": "https://o-plus.site/staff.html",
    "Offsuit": "https://offsuit.site/therapist",
    "Queendom": "https://omiya-mens-este.net/therapist.html",
}

MAX_PAGES = 10          # 1店舗あたり最大何ページまで「次のページ」をたどるか
MIN_COVERAGE = 0.8      # 今週の出勤者のうち何割が一覧で見つかれば「判定する」にするか
PAGINATION_PATTERN = re.compile(r"/page/\d+|[?&](page|p|pg|paged)=\d+")

# 名前として扱う文字（ひらがな・カタカナ・漢字・長音・英数字）
NAME_CHARS = r"ぁ-んァ-ヶー一-龠々〆\u3400-\u9fffA-Za-z0-9Ａ-Ｚａ-ｚ０-９"
NON_NAME_RE = re.compile(rf"[^{NAME_CHARS}]+")
SPACE_RE = re.compile(r"[\s\u3000]+")


def norm(text):
    """空白を詰め、名前に使わない記号は区切り「|」に置き換える（アプリ側と同じルール）"""
    text = SPACE_RE.sub("", text or "")
    text = NON_NAME_RE.sub("|", text)
    return text


def norm_name(name):
    return norm(name).strip("|")


def name_found(name, text):
    """一覧テキストの中に、その名前が「単独の名前として」含まれているか"""
    n = norm_name(name)
    if not n:
        return False
    # 前がひらがな、または後ろが名前の文字の続きの場合は別人とみなす
    # 例: 「もも」は「ももか」の中では見つからない扱い
    pattern = rf"(?<![ぁ-ん]){re.escape(n)}(?![ぁ-んァ-ヶー一-龠々\u3400-\u9fff])"
    return re.search(pattern, text) is not None


def collect_text(page):
    """ページを下までスクロールし、本文と画像のalt等の文字を集める"""
    for _ in range(4):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(700)
    body = page.inner_text("body")
    extra = page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('img[alt], [title]').forEach(el => {
                if (el.alt) out.push(el.alt);
                if (el.title) out.push(el.title);
            });
            return out;
        }"""
    )
    parts = body.split("\n") + list(extra)
    pieces = []
    for p in parts:
        p = p.strip()
        if not p or len(p) > 120:
            continue
        if not re.search(r"[ぁ-んァ-ヶ一-龠]", p):
            continue
        pieces.append(norm(p))
    return pieces


def pagination_links(page, base_url):
    host = urlparse(base_url).netloc
    hrefs = page.evaluate(
        "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"
    )
    links = []
    for h in hrefs:
        if not h or h.startswith("javascript"):
            continue
        full = urljoin(page.url, h).split("#")[0]
        if urlparse(full).netloc != host:
            continue
        if PAGINATION_PATTERN.search(full):
            links.append(full)
    return links


def fetch_roster(browser, url):
    page = browser.new_page()
    page.set_default_timeout(30000)
    pieces = []
    visited = set()
    queue = [url]
    try:
        while queue and len(visited) < MAX_PAGES:
            target = queue.pop(0)
            if target in visited:
                continue
            visited.add(target)
            page.goto(target, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            pieces.extend(collect_text(page))
            for link in pagination_links(page, url):
                if link not in visited and link not in queue:
                    queue.append(link)
    finally:
        page.close()
    # 重複を除いて「|」でつなぐ
    seen = set()
    uniq = []
    for p in pieces:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return "|" + "|".join(uniq) + "|", len(visited)


def load_schedule_names():
    """data/*.json から、店舗ごとの今週の出勤者名を集める"""
    result = {}
    for path in glob.glob(os.path.join(DATA_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            shop = d.get("shop")
            if not shop:
                continue
            names = {t["name"] for t in d.get("therapists", []) if t.get("name")}
            result.setdefault(shop, set()).update(names)
        except Exception as e:
            print(f"[警告] {path} を読めませんでした: {e}")
    return result


def load_previous():
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f).get("shops", {})
    except Exception:
        return {}


def main():
    schedule_names = load_schedule_names()
    previous = load_previous()
    shops = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for shop, url in ROSTER_URLS.items():
            try:
                text, pages = fetch_roster(browser, url)
            except Exception as e:
                print(f"{shop}: 読み込み失敗 → 前回のデータを使います（{e}）")
                if shop in previous:
                    shops[shop] = previous[shop]
                continue

            names = sorted(schedule_names.get(shop, set()))
            found = [n for n in names if name_found(n, text)]
            missing = [n for n in names if not name_found(n, text)]
            coverage = (len(found) / len(names)) if names else 0.0
            ok = len(names) > 0 and coverage >= MIN_COVERAGE

            print(
                f"{shop}: {pages}ページ読込 / 今週の出勤者 {len(found)}/{len(names)}名 が一覧に存在"
                f"（{coverage:.0%}）→ {'判定する' if ok else '判定しない'}"
            )
            if missing:
                print(f"    一覧で見つからなかった名前: {'、'.join(missing[:30])}")

            if not ok and shop in previous and previous[shop].get("ok"):
                print("    → 今回は確認が不十分なため、前回のデータを使います")
                shops[shop] = previous[shop]
                continue

            shops[shop] = {
                "ok": ok,
                "url": url,
                "coverage": round(coverage, 3),
                "checked_at": datetime.datetime.now(JST).isoformat(timespec="seconds"),
                "text": text,
            }
        browser.close()

    out = {
        "generated_at": datetime.datetime.now(JST).isoformat(timespec="seconds"),
        "shops": shops,
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"保存しました: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
