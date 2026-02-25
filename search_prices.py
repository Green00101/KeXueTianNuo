# -*- coding: utf-8 -*-
"""
查价模块：根据物品中文名查询 Warframe Market 价格。
可被 ocr.py / ocr_rapid.py 调用，也可单独运行以调试查价逻辑。
"""
import os
import re
import sys
import time
import requests
import pandas as pd
from collections import Counter


def _normalize_cn_key(s):
    """查价用：去掉所有空白（含全角、不间断空格等）并小写，便于与 CSV 一致匹配。"""
    if not s or not isinstance(s, str):
        return ""
    return re.sub(r"\s+", "", s).lower()

# 请求间隔（秒），避免瞬时过多请求
WFM_REQUEST_INTERVAL = 0.4
_last_wfm_request_time = [0.0]

# 资源路径：与当前脚本同目录
def _resource_path(relative_path):
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


def _load_cn2url():
    """加载 CSV，键与 _normalize_cn_key 完全一致，保证 UI/命令行同一套逻辑。"""
    csv_path = _resource_path('wfm_item_names_en_zh.csv')
    df = pd.read_csv(csv_path, dtype=str, encoding='utf-8')
    # 建表时就用规范化键，与查找时 _normalize_cn_key 一致（去所有空白+小写）
    df["_key"] = df["Chinese"].fillna("").apply(lambda s: _normalize_cn_key(str(s)))
    return dict(zip(df["_key"], df["url_name"]))


def _ocr_correct(s):
    t = s
    t = t.replace('Prlime', 'Prime').replace('Prlme', 'Prime').replace('Prirne', 'Prime').replace('Prirre', 'Prime')
    t = t.replace('Prirrle', 'Prime').replace('Prirlls', 'Prime').replace('Frme', 'Prime')
    t = t.replace('Pr me', 'Prime ').replace('Pr me ', 'Prime ')
    t = t.replace('Forrna', 'Forma').replace('ForIrig', 'Forma')
    if 'Iara ' in t or (len(t) >= 4 and t[:4] == 'Iara'):
        t = t.replace('Iara ', 'Ivara ', 1).replace('Iara', 'Ivara', 1)
    return t


def get_wfm_prices(item_en_name):
    """请求 WFM API 获取该物品卖单，取价格最低的前 5 条。失败返回 None。"""
    global _last_wfm_request_time
    now = time.monotonic()
    if now - _last_wfm_request_time[0] < WFM_REQUEST_INTERVAL:
        time.sleep(WFM_REQUEST_INTERVAL - (now - _last_wfm_request_time[0]))
    _last_wfm_request_time[0] = time.monotonic()
    # v2 文档：https://42bytes.notion.site/WFM-Api-v2-Documentation-5d987e4aa2f74b55a80db1a09932459d
    # 查价路径：/v2/orders/item/{url_name}
    url = f'https://api.warframe.market/v2/orders/item/{item_en_name}'
    headers = {'accept': 'application/json'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        return None
    if r.status_code != 200:
        return None
    body = r.json()
    # v2 实际返回: data[] 中每项为 type/platinum/user（字段名为 type 不是 order_type）
    orders = body.get("data") if isinstance(body.get("data"), list) else []
    # 卖单且必须 user.status == "ingame"；按 platinum 升序取前 5 条
    sell_ingame = [o for o in orders
                   if (o.get("type") or o.get("order_type")) == "sell"
                   and (o.get("user") or {}).get("status") == "ingame"]
    orders = sorted(sell_ingame, key=lambda x: x.get("platinum") or 0)[:5]
    counter = Counter([o["platinum"] for o in orders if "platinum" in o])
    return counter if counter else None


def search_prices_from_merged_items(merged_items):
    """
    根据识别出的物品名列表查价。
    merged_items: list of dict，每项需有 'text' 键（物品中文名）
    返回: list of str（每条查价结果一行）
    """
    results = []
    # 表键已是 _normalize_cn_key 形式，与 UI/命令行同一套逻辑
    cn2url = _load_cn2url()

    def find_en_by_cn(cn):
        key = _normalize_cn_key(cn)
        return cn2url.get(key, None)

    for item in merged_items:
        raw = (item.get('text') or '').strip()
        zh = _ocr_correct(raw)
        if 'Forma' in zh or 'forma' in zh.lower():
            results.append(f"{zh}：未收录")
            continue
        search_zh = zh + '图' if zh.endswith('蓝') else zh
        en = find_en_by_cn(search_zh)
        if en:
            price_counter = get_wfm_prices(en)
            if price_counter:
                price_list = [f"{price}p×{count}人" for price, count in price_counter.items()]
                results.append(f"{search_zh if search_zh != zh else zh}：{', '.join(price_list)}")
            else:
                results.append(f"{search_zh if search_zh != zh else zh}：无有效卖单")
        else:
            zh_key = _normalize_cn_key(search_zh)
            # 模糊：与表中键长度相同且仅差 1 字（表中键已是规范化键）
            fuzzy_list = [(zh_db, en_db) for zh_db, en_db in cn2url.items()
                          if len(zh_db) == len(zh_key) and sum(a != b for a, b in zip(zh_db, zh_key)) == 1]
            if fuzzy_list:
                display_name = search_zh if search_zh != zh else zh
                results.append(f"模糊搜索  '{display_name}'结果：")
                for zh_match, en_fuzzy in fuzzy_list:
                    price_counter = get_wfm_prices(en_fuzzy)
                    results.append(f"  {zh_match}：{', '.join(f'{p}p×{c}人' for p, c in price_counter.items())}" if price_counter else f"  {zh_match}：无有效卖单")
            else:
                less_one_list = [(zh_db, en_db) for zh_db, en_db in cn2url.items()
                                 if len(zh_db) == len(zh_key) + 1 and zh_db[:-1] == zh_key]
                if less_one_list:
                    display_name = search_zh if search_zh != zh else zh
                    results.append(f"少一字匹配  '{display_name}'结果：")
                    for zh_match, en_fuzzy in less_one_list:
                        price_counter = get_wfm_prices(en_fuzzy)
                        results.append(f"  {zh_match}：{', '.join(f'{p}p×{c}人' for p, c in price_counter.items())}" if price_counter else f"  {zh_match}：无有效卖单")
                else:
                    results.append(f"模糊搜索'{search_zh if search_zh != zh else zh}'无匹配结果")
    return results


# 直接传入物品名列表也可查价（会转成 merged_items 格式）
def search_prices_from_names(names):
    """names: list of str，物品中文名。返回查价结果列表。"""
    merged_items = [{'text': n} for n in names]
    return search_prices_from_merged_items(merged_items)


if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    # 用刚刚 OCR 的识别结果做查价调试
    test_4png = [
        "威震武扇 Prime 蓝图",
        "雷克斯 Prime 枪机",
    ]
    test_real = [
        "Forma 蓝图",
        "Forma",
        "Ivara Prime 机体蓝图",
        "电幻步枪 Prime 枪机",
    ]
    print("=== 4.png 识别结果查价 ===")
    for line in search_prices_from_names(test_4png):
        print(line)
    print()
    print("=== real.png 识别结果查价 ===")
    for line in search_prices_from_names(test_real):
        print(line)
