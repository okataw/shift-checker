# -*- coding: utf-8 -*-
"""
「グリーンアップル」(https://greenapple-esthe.com/schedule) の出勤データを
公式サイトから取得するスクリプト。

このサイトは日付ごとに
  https://greenapple-esthe.com/schedule?day=2026-11-25&from=2026-11-25
のようなURLで1日分の出勤表が表示されるので、7日分を順に読み込む。

・セラピストの個人ページ（/therapist/数字）へのリンクの文字から名前を取る
・同じカードの中の「○○ルーム」からルーム名を取る
・個人ページのURLも保存する（アプリで名前をタップしたときに開くため）
・結果を data/greenapple.json に保存する
・読み込みに失敗した日は、前回取れていたデータをそのまま使う
"""
import datetime
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間

SHOP_NAME = "グリーンアップル"
REGION = "神奈川"
SITE_ROOT = "https://greenapple-esthe.com"
SCHEDULE_URL = SITE_ROOT + "/schedule?day={day}&from={start}"
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "greenapple.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; shift-checker personal schedule viewer)",
    "Accept-Language": "ja,en;q=0.8",
}
PROFILE_RE = re.compile(r"^(?:https?://[^/]+)?/therapist/(\d+)/?$")
ROOM_RE = re.compile(r"([^\s　]{1,10})ルーム")
# 出勤しているカードには「21:30〜5:10」のような時間か「○○ルーム」が書かれている
# （ページの端にある「新人」「ランキング」などの欄の人を、出勤者と間違えないため）
SHIFT_RE = re.compile(r"\d{1,2}:\d{2}\s*[〜~～-]|ルーム")
MAX_RETRY = 3


def fetch(url):
    last_error = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            res = requests.get(url, headers=HEADERS, timeout=30)
            print(f"  応答 {res.status_code} / {len(res.content)}バイト")
            res.raise_for_status()
            res.encoding = res.apparent_encoding or "utf-8"
            return res.text
        except Exception as e:
            last_error = e
            print(f"  [再試行 {attempt}/{MAX_RETRY}] {e}")
            time.sleep(3)
    raise last_error


def card_of(link, therapist_id):
    """そのセラピストのリンクだけを含む、一番大きい枠（カード）を探す"""
    box = link
    while box.parent is not None and box.parent.name not in ("body", "html", "[document]"):
        ids = set()
        for a in box.parent.find_all("a", href=True):
            m = PROFILE_RE.match(a["href"])
            if m:
                ids.add(m.group(1))
        if ids - {therapist_id}:
            break  # 他の人のリンクまで含む範囲になったら止める
        box = box.parent
    return box


def parse_day(html):
    """1日分のページから [(名前, ルーム, 個人ページURL), ...] を取り出す"""
    soup = BeautifulSoup(html, "html.parser")
    result = []
    seen_ids = set()
    for a in soup.find_all("a", href=True):
        m = PROFILE_RE.match(a["href"])
        if not m:
            continue
        name = a.get_text(" ", strip=True)
        if not name or not re.search(r"[ぁ-んァ-ヶ一-龠]", name):
            continue  # 写真だけのリンクなどは飛ばす
        therapist_id = m.group(1)
        if therapist_id in seen_ids:
            continue
        seen_ids.add(therapist_id)
        card = card_of(a, therapist_id)
        card_text = card.get_text(" ", strip=True)
        if not SHIFT_RE.search(card_text):
            continue  # 出勤時間もルームも書かれていない欄（ランキング等）は出勤者として数えない
        rm = ROOM_RE.search(card_text)
        room = rm.group(1) if rm else ""
        result.append((name, room, f"{SITE_ROOT}/therapist/{therapist_id}"))
    return result


def load_previous():
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    today = datetime.datetime.now(JST).date()  # 日本時間の「今日」
    week_dates = [today + datetime.timedelta(days=i) for i in range(7)]
    previous = load_previous() or {}
    prev_schedule = previous.get("schedule", {})
    prev_info = {t["name"]: t for t in previous.get("therapists", [])}

    schedule = {}
    info = {}
    success = 0
    for d in week_dates:
        day = d.isoformat()
        url = SCHEDULE_URL.format(day=day, start=today.isoformat())
        try:
            entries = parse_day(fetch(url))
            success += 1
        except Exception as e:
            print(f"[警告] {day} の取得に失敗しました → 前回のデータを使います: {e}")
            names = prev_schedule.get(day, [])
            schedule[day] = names
            for n in names:
                if n in prev_info:
                    info[n] = prev_info[n]
            print(f"{day}: {len(names)}名（前回のデータ）")
            continue

        names = []
        for name, room, profile in entries:
            names.append(name)
            if name not in info or (room and not info[name].get("area")):
                info[name] = {"name": name, "area": room, "url": profile}
        schedule[day] = names
        print(f"{day}: {len(names)}名 出勤確認  例: {'、'.join(names[:5])}")
        time.sleep(1.0)

    print(f"（今回取得できた日数: {success}/7）")

    output = {
        "shop": SHOP_NAME,
        "region": REGION,
        "updated_at": (datetime.datetime.now(JST).isoformat(timespec="seconds")
                       if success > 0 else previous.get("updated_at", "")),
        "dates": [d.isoformat() for d in week_dates],
        "therapists": [info[n] for n in sorted(info)],
        "schedule": schedule,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
