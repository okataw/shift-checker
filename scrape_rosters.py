"""
各店舗ホームページの「セラピスト一覧（在籍一覧）」ページを読み込み、
在籍しているセラピスト名の手がかりとなる文字列を docs/rosters.json に保存する。

アプリ側では、★登録しているのに今週の出勤表に載っていない人について、
この一覧に名前が無ければ「退店済」と赤字で表示する。
また、一覧ページにある「名前 → 個人ページ」のリンクも保存し、
アプリで名前をタップしたときに個人ページを開けるようにする。

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
    # アロマモアは一覧ページが外部からのアクセスを拒否（403 Forbidden）しているため対象外
    "トキョプラ": "https://tokyopla.com/therapist",
    "Tigger": "https://tigger-esthe.com/therapist",
    "アマテラス横浜": "https://amaterasu-yokohama.com/therapist",
    "LINDA SPA": "https://linda-spa.com/cast/",
    "NEW+PLUS": "https://o-plus.site/staff.html",
    "Offsuit": "https://offsuit.site/therapist",
    "Queendom": "https://omiya-mens-este.net/therapist.html",
}

MAX_PAGES = 10          # 1店舗あたり最大何ページまで「次のページ」をたどるか
MAX_ATTEMPTS = 2        # 読み込みに失敗したときに何回まで試すか
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
    # 画像のalt・title、リンクの文字、ページ全体のHTML内の文字も集める
    # （名前が画像だけ・リンクの中だけに書かれているサイトにも対応するため）
    extra = page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('img[alt], [title]').forEach(el => {
                if (el.alt) out.push(el.alt);
                if (el.title) out.push(el.title);
            });
            document.querySelectorAll('a').forEach(a => {
                const t = (a.textContent || '').trim();
                if (t) out.push(t);
            });
            out.push(document.body ? (document.body.textContent || '') : '');
            return out;
        }"""
    )
    parts = body.split("\n") + list(extra)
    pieces = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not re.search(r"[ぁ-んァ-ヶ一-龠]", p):
            continue
        pieces.append(norm(p))
    return pieces


def debug_page(browser, url):
    """判定できなかった店舗について、原因を探るためにページの様子を表示する"""
    page = browser.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        body = page.inner_text("body")
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        links = page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href') + ' | ' + (a.textContent||'').trim().slice(0,30))"
        )
        print(f"    [調査] 表示されたURL: {page.url}")
        print(f"    [調査] ページタイトル: {page.title()}")
        print(f"    [調査] 本文の行数: {len(lines)} / リンク数: {len(links)}")
        for l in lines[:25]:
            print(f"    [調査] 本文: {l[:80]}")
        for l in links[:40]:
            print(f"    [調査] リンク: {l[:100]}")
    except Exception as e:
        print(f"    [調査] 失敗: {e}")
    finally:
        page.close()


def collect_profile_links(page, base_url):
    """一覧ページ内のリンクのうち、名前らしき文字を含むものを [文字, URL] で集める"""
    host = urlparse(base_url).netloc
    # リンク自体に名前が書かれていない場合（写真だけのリンクなど）は、
    # そのリンクを囲む枠（同じ人のリンクしか含まない範囲）の文字を名前の手がかりにする
    items = page.evaluate(
        """() => {
            const jp = /[ぁ-んァ-ヶ一-龠]/;
            const ownText = a => {
                const alts = Array.from(a.querySelectorAll('img[alt]')).map(i => i.alt).join(' ');
                return ((a.innerText || '') + ' ' + alts).trim();
            };
            return Array.from(document.querySelectorAll('a[href]')).map(a => {
                let text = ownText(a);
                if (!jp.test(text)) {
                    let el = a.parentElement;
                    for (let depth = 0; el && depth < 5; depth++, el = el.parentElement) {
                        const hrefs = new Set(Array.from(el.querySelectorAll('a[href]')).map(x => x.href));
                        if (hrefs.size > 1) break;   // 他の人のリンクまで含む範囲になったら止める
                        const t = (el.innerText || '').trim();
                        if (jp.test(t)) { text = t; break; }
                    }
                }
                return [text, a.href];
            });
        }"""
    )
    links = []
    base = base_url.rstrip("/")
    for text, href in items:
        if not href or href.startswith("javascript"):
            continue
        href = href.split("#")[0]
        if urlparse(href).netloc != host or href.rstrip("/") == base:
            continue
        if PAGINATION_PATTERN.search(href):
            continue
        if not text or len(text) > 200 or not re.search(r"[ぁ-んァ-ヶ一-龠]", text):
            continue
        links.append([norm(text).strip("|"), href])
    return links


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
    links = []
    visited = set()
    queue = [url]
    try:
        while queue and len(visited) < MAX_PAGES:
            target = queue.pop(0)
            if target in visited:
                continue
            visited.add(target)
            page.goto(target, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            pieces.extend(collect_text(page))
            links.extend(collect_profile_links(page, url))
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
    # リンクも重複を除く
    seen_links = set()
    uniq_links = []
    for text, href in links:
        if (text, href) not in seen_links:
            seen_links.add((text, href))
            uniq_links.append([text, href])
    return "|" + "|".join(uniq) + "|", uniq_links, len(visited)


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
            text, links, pages, error = None, [], 0, None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    text, links, pages = fetch_roster(browser, url)
                    break
                except Exception as e:
                    error = str(e).split("\n")[0]
                    print(f"  [再試行 {attempt}/{MAX_ATTEMPTS}] {shop}: {error}")
            if text is None:
                if shop in previous:
                    print(f"{shop}: 読み込み失敗 → 前回のデータを使います")
                    shops[shop] = previous[shop]
                else:
                    print(f"{shop}: 読み込み失敗（前回のデータも無いため、今回は判定しません）")
                continue

            names = sorted(schedule_names.get(shop, set()))
            found = [n for n in names if name_found(n, text)]
            missing = [n for n in names if not name_found(n, text)]
            coverage = (len(found) / len(names)) if names else 0.0
            ok = len(names) > 0 and coverage >= MIN_COVERAGE

            linked = [n for n in names if any(name_found(n, "|" + t + "|") for t, _ in links)]
            print(
                f"{shop}: {pages}ページ読込 / 今週の出勤者 {len(found)}/{len(names)}名 が一覧に存在"
                f"（{coverage:.0%}）→ {'判定する' if ok else '判定しない'}"
                f" / 個人ページのリンク {len(linked)}/{len(names)}名"
            )
            if missing:
                print(f"    一覧で見つからなかった名前: {'、'.join(missing[:30])}")
            if not ok:
                debug_page(browser, url)

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
                "links": links,
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
