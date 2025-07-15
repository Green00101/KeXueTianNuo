import cv2
import numpy as np
import easyocr
import pandas as pd
import requests
import sys
import os
from collections import Counter

def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容开发环境和打包后的环境"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller创建临时文件夹，并将路径存储在_MEIPASS中
        base_path = getattr(sys, '_MEIPASS')
    else:
        # 开发环境中使用当前脚本的目录
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

# 全局EasyOCR reader，避免重复初始化
_ocr_reader = None

def get_ocr_reader():
    """获取OCR reader，如果不存在则创建"""
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(['ch_sim', 'en'])
    return _ocr_reader

def ocr_and_search_prices(ori_img):
    """
    OCR识别图片中的物品并查询Warframe Market价格
    
    参数:
        ori_img: 输入图片路径或numpy数组
        
    返回:
        list: 包含所有识别和搜索结果的列表
    """
    results = []
    
    # ---- 步骤1：提取黄色文字，生成白底黄字图 ----
    if isinstance(ori_img, str):
        img = cv2.imread(ori_img)
    else:
        img = ori_img
        
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lower_yellow = np.array([20, 100, 150])
    upper_yellow = np.array([26, 255, 255])
    mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

    # 白底
    white_bg = np.ones_like(img) * 255
    result = cv2.bitwise_and(img, img, mask=mask)
    inv_mask = cv2.bitwise_not(mask)
    white_part = cv2.bitwise_and(white_bg, white_bg, mask=inv_mask)
    final = cv2.add(result, white_part)
    cv2.imwrite('yellow_on_white_ori.png', final)

    # ---- 步骤2：自动裁剪文字区域 ----
    # img = cv2.imread('yellow_on_white_ori.png')
    # gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # _, binary = cv2.threshold(gray, 250, 255, cv2.THRESH_BINARY_INV)
    # horizontal_sum = np.sum(binary, axis=1)
    # rows = np.where(horizontal_sum > 0)[0]
    # if len(rows) > 0:
    #     top, bottom = rows[0], rows[-1]
    # else:
    #     top, bottom = 0, binary.shape[0]-1

    # vertical_sum = np.sum(binary, axis=0)
    # cols = np.where(vertical_sum > 0)[0]
    # if len(cols) > 0:
    #     left, right = cols[0], cols[-1]
    # else:
    #     left, right = 0, binary.shape[1]-1

    # cropped = img[top:bottom+1, left:right+1]
    # cv2.imwrite('cropped.png', cropped)

    # ---- 步骤3：EasyOCR识别文字，进行包含合并 ----
    reader = get_ocr_reader()  # 使用全局reader，避免重复初始化
    
    # 直接从处理后的图像进行OCR，避免文件读写
    if isinstance(ori_img, str):
        result = reader.readtext(ori_img, detail=1)
    else:
        # 如果是numpy数组，直接使用
        result = reader.readtext(final, detail=1)

    # 3. 画bbox到图片上
    # for bbox, text, conf in result:
    #     # 将裁剪后的坐标转换为原始图片坐标
    #     pts = [(int(float(x) + int(left)), int(float(y) + int(top))) for x, y in bbox]
    #     # 画多边形框线，pts顺序通常是左上-右上-右下-左下
    #     cv2.polylines(img, [np.array(pts)], isClosed=True, color=(0,255,0), thickness=2)

    # # 4. 保存结果图片
    # cv2.imwrite('ocr_boxed.png', img)
    #results.append('已保存带框图片 ocr_boxed.png')
    
    # 转结构化list
    items = []
    for bbox, text, conf in result:
        x1 = int(bbox[0][0])
        x2 = int(bbox[2][0])
        if x1 > x2:
            x1, x2 = x2, x1
        items.append({'x1': x1, 'x2': x2, 'text': text, 'merged': False})

    # 包含合并逻辑
    # 记录被合并掉的元素的下标
    merged_indices = []
    for i, item_a in enumerate(items):
        for j in range(i + 1, len(items)):
            item_b = items[j]
            if item_a['x1'] <= item_b['x1'] and item_a['x2'] >= item_b['x2']:
                item_b['text'] = item_a['text'] + item_b['text']
                merged_indices.append(i)  # 不去重，每次合并都记一次

    # 按下标逆序删除，避免下标错位
    for idx in sorted(set(merged_indices), reverse=True):
        del items[idx]

    # 输出最终结果
    #results.append("最终合并结果：")
    #for item in items:
    #    if not item['merged']:
    #        results.append(item['text'])

    csv_path = get_resource_path('wfm_item_names_en_zh.csv')
    df_map = pd.read_csv(csv_path)
    df_map['Chinese_nospace'] = df_map['Chinese'].str.replace(' ', '')
    cn2url = dict(zip(df_map['Chinese_nospace'], df_map['url_name']))

    def find_en_by_cn(cn):
        # 查找前先去空格，并转换为小写
        cn_nospace = cn.replace(' ', '').lower()
        # 创建小写版本的映射字典
        cn2url_lower = {k.lower(): v for k, v in cn2url.items()}
        return cn2url_lower.get(cn_nospace, None)

    # ---- 查warframe market售价 ----
    def get_wfm_prices(item_en_name):
        url = f'https://api.warframe.market/v1/items/{item_en_name}/orders'
        headers = {
            'accept': 'application/json'
        }
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            return None
        data = r.json()
        if "payload" not in data or "orders" not in data["payload"]:
            return None
        # 只统计卖家且为在售状态
        orders = [o for o in data["payload"]["orders"] if o["order_type"]=="sell" and o["user"]["status"]=="ingame"]
        # 前10名
        orders = sorted(orders, key=lambda x: x['platinum'])[:10]
        price_counter = Counter([o['platinum'] for o in orders])
        return price_counter

    exact_found = []
    need_fuzzy = []
    #results.append(f"OCR识别结果：{', '.join(item['text'] for item in items)}")
    
    for item in items:
        zh = item['text']
        
        # 检查是否包含Forma关键字
        if 'Forma' in zh or 'forma' in zh.lower():
            results.append(f"{zh}：未收录")
            continue
        
        # 如果以'蓝'结尾，先加上'图'再匹配
        search_zh = zh
        if zh.endswith('蓝'):
            search_zh = zh + '图'
        
        en = find_en_by_cn(search_zh)
        if en:
            # ---- 精确匹配查价 ----
            price_counter = get_wfm_prices(en)
            if price_counter:
                price_list = [f"{price}p×{count}人" for price, count in price_counter.items()]
                # 如果使用了修正后的名称，显示修正信息
                if search_zh != zh:
                    results.append(f"{search_zh}：{', '.join(price_list)}")
                else:
                    results.append(f"{zh}：{', '.join(price_list)}")
            else:
                # 如果使用了修正后的名称，显示修正信息
                if search_zh != zh:
                    results.append(f"{search_zh}：无有效卖单")
                else:
                    results.append(f"{zh}：无有效卖单")
        else:
            # ---- 模糊搜索1字偏差（忽略空格，不区分大小写） ----
            zh_text_nospace = search_zh.replace(' ', '').lower()
            fuzzy_list = []
            for zh_db, en_db in cn2url.items():
                zh_db_lower = zh_db.lower()
                if len(zh_db_lower) == len(zh_text_nospace):
                    diff = sum(a != b for a, b in zip(zh_db_lower, zh_text_nospace))
                    if diff == 1:
                        fuzzy_list.append((zh_db, en_db))
            if fuzzy_list:
                display_name = search_zh if search_zh != zh else zh
                results.append(f"模糊搜索  '{display_name}'结果：")
                for zh_match, en_fuzzy in fuzzy_list:
                    price_counter = get_wfm_prices(en_fuzzy)
                    if price_counter:
                        price_list = [f"{price}p×{count}人" for price, count in price_counter.items()]
                        results.append(f"  {zh_match}：{', '.join(price_list)}")
                    else:
                        results.append(f"  {zh_match}：无有效卖单")
            else:
                # ---- 少一字匹配（词库里的词比识别出的词多一个字，且只能是最后一个字，不区分大小写） ----
                less_one_list = []
                for zh_db, en_db in cn2url.items():
                    zh_db_lower = zh_db.lower()
                    # 词库中的词长度比识别出的词长度多1
                    if len(zh_db_lower) == len(zh_text_nospace) + 1:
                        # 检查词库中的词去掉最后一个字符后是否与识别出的词完全匹配
                        if zh_db_lower[:-1] == zh_text_nospace:
                            less_one_list.append((zh_db, en_db))
                
                if less_one_list:
                    display_name = search_zh if search_zh != zh else zh
                    results.append(f"少一字匹配  '{display_name}'结果：")
                    for zh_match, en_fuzzy in less_one_list:
                        price_counter = get_wfm_prices(en_fuzzy)
                        if price_counter:
                            price_list = [f"{price}p×{count}人" for price, count in price_counter.items()]
                            results.append(f"  {zh_match}：{', '.join(price_list)}")
                        else:
                            results.append(f"  {zh_match}：无有效卖单")
                else:
                    # 使用修正后的名称显示搜索结果
                    display_name = search_zh if search_zh != zh else zh
                    results.append(f"模糊搜索'{display_name}'无匹配结果")
    
    return results


# 为了保持向后兼容，如果直接运行此文件，使用默认参数
if __name__ == "__main__":
    results = ocr_and_search_prices('yellow_on_white_ori.png')
    for result in results:
        print(result)