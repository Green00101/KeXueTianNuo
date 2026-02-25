# -*- coding: utf-8 -*-
"""
从 Warframe Market API v2 拉取物品列表，更新 wfm_item_names_en_zh.csv。
官方 v2 文档：https://42bytes.notion.site/WFM-Api-v2-Documentation-5d987e4aa2f74b55a80db1a09932459d
GET /v2/items 返回 { apiVersion, data: [ ItemShort, ... ], error: null }，需用 data 数组。
API 免费、公开；请求已加间隔，限速约 3 请求/秒。
"""
import csv
import os
import sys
import time
import requests

WFM_REQUEST_INTERVAL = 0.5
# v2 物品列表：GET /v2/items，响应为 { data: [ ItemShort, ... ] }
API_ITEMS = "https://api.warframe.market/v2/items"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wfm_item_names_en_zh.csv")


def fetch_items(lang="en"):
    """请求 /v2/items，Language 头决定 item_name 语言。v2 响应用 data 数组，非 payload.items。"""
    headers = {"accept": "application/json", "Language": lang}
    r = requests.get(API_ITEMS, headers=headers, timeout=30)
    r.raise_for_status()
    body = r.json()
    # v2: { apiVersion, data: [ ItemShort, ... ], error: null }
    lst = body.get("data") if isinstance(body.get("data"), list) else []
    out = {}
    for it in lst:
        slug = it.get("url_name") or it.get("slug")
        if not slug:
            continue
        name = it.get("item_name") or (it.get("i18n") or {}).get(lang, {}).get("item_name") or ""
        out[slug] = name
    return out


def main():
    print("请求英文列表...")
    en_map = fetch_items("en")
    time.sleep(WFM_REQUEST_INTERVAL)
    print("请求中文列表...")
    zh_map = fetch_items("zh-hans")
    # 以英文键为准，缺中文的保留空或英文
    rows = []
    for url_name in sorted(en_map.keys()):
        en = en_map.get(url_name) or ""
        zh = zh_map.get(url_name) or en
        rows.append((url_name, en, zh))
    print(f"共 {len(rows)} 条，写入 {OUTPUT_CSV}")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url_name", "English", "Chinese"])
        w.writerows(rows)
    print("完成。")


if __name__ == "__main__":
    main()
    sys.exit(0)
