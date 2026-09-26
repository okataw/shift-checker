# -*- coding: utf-8 -*-
"""
アロマモア公式サイト(https://aromamore.tokyo/scheduleAll.html)の
ページ構造を調べるための、一時的な調査用スクリプト。
データの保存は行わず、ページの中身をログに表示するだけ。
（調査が終わったら削除してOK）
"""
import re
from playwright.sync_api import sync_playwright

URL = "https://aromamore.tokyo/scheduleAll.html"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ))
    page.goto(URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    print("===== タイトル =====")
    print(page.title())

    print("===== 画面の文字(先頭120行) =====")
    lines = [l.strip() for l in page.inner_text("body").splitlines() if l.strip()]
    for l in lines[:120]:
        print(l)

    print("===== リンク一覧(先頭60件) =====")
    links = page.eval_on_selector_all(
        "a", "els => els.map(e => [e.getAttribute('href'), e.innerText.trim().replace(/\\s+/g,' ')])"
    )
    for href, text in links[:60]:
        print(f"{href} | {text[:40]}")

    browser.close()
