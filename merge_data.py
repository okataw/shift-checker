# -*- coding: utf-8 -*-
"""
data/ フォルダの中にある各店舗のJSON（kibun.json など）をすべて読み込み、
アプリ表示用の1つのファイル docs/data.json にまとめる。

新しい店舗を追加したときは、その店舗のスクレイパーが
data/店舗名.json を { shop, region, dates, therapists, schedule } の形式で
出力するようにすれば、このスクリプトは変更なしでそのまま使える。
"""
import json
import os
import glob
import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))  # 日本時間

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "data.json")


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    regions = {}

    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            shop_data = json.load(f)

        region = shop_data.get("region", "その他")
        regions.setdefault(region, {"therapists": [], "dates": None, "schedule": {}})

        # 日付リストは店舗間でズレる可能性があるが、今回は最初に見つかったものを採用
        if regions[region]["dates"] is None:
            regions[region]["dates"] = shop_data["dates"]

        for t in shop_data["therapists"]:
            shop_name = shop_data.get("shop", "")
            key = f"{shop_name}::{t['name']}"
            regions[region]["therapists"].append({
                "key": key,
                "name": t["name"],
                "area": t.get("area", ""),
                "shop": shop_name,
            })

        shop_name = shop_data.get("shop", "")
        for date_str, names in shop_data.get("schedule", {}).items():
            regions[region]["schedule"].setdefault(date_str, {})
            for name in names:
                key = f"{shop_name}::{name}"
                regions[region]["schedule"][date_str][key] = True

    output = {
        "generated_at": datetime.datetime.now(JST).isoformat(timespec="seconds"),
        "regions": regions,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"まとめました: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
