import cv2
import numpy as np
import easyocr
import pandas as pd
import requests
import sys
import os
import json
import logging
from collections import Counter

# 获取或创建日志记录器
def get_logger():
    """获取日志记录器"""
    return logging.getLogger('WFOCR')

def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容开发环境和打包后的环境"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller创建临时文件夹，并将路径存储在_MEIPASS中
        base_path = getattr(sys, '_MEIPASS')
    else:
        # 开发环境中使用当前脚本的目录
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

def setup_easyocr_model_path():
    """设置EasyOCR模型路径，兼容打包环境"""
    logger = get_logger()
    if hasattr(sys, '_MEIPASS'):
        # 在打包环境中，模型文件被包含在临时目录中
        model_base_path = get_resource_path('.EasyOCR')
        model_path = os.path.join(model_base_path, 'model')
        
        logger.info(f"检查打包模型路径: {model_path}")
        if os.path.exists(model_path):
            # 检查是否有模型文件
            model_files = [f for f in os.listdir(model_path) if f.endswith('.pth')]
            logger.info(f"找到模型文件: {model_files}")
            
            if model_files:
                # 设置EasyOCR的模型目录环境变量
                os.environ['EASYOCR_MODULE_PATH'] = model_base_path
                logger.info(f"设置EasyOCR模型路径: {model_base_path}")
                return model_base_path
            else:
                logger.warning(f"模型目录存在但没有找到.pth文件: {model_path}")
        else:
            logger.warning(f"打包模型路径不存在: {model_path}")
    
    # 检查开发环境的本地模型
    local_model_path = '.EasyOCR'
    if os.path.exists(local_model_path):
        local_model_files_path = os.path.join(local_model_path, 'model')
        if os.path.exists(local_model_files_path):
            model_files = [f for f in os.listdir(local_model_files_path) if f.endswith('.pth')]
            if model_files:
                logger.info(f"使用本地EasyOCR模型: {local_model_path}")
                return local_model_path
    
    logger.info("未找到本地模型，将使用默认路径")
    return None

# 全局EasyOCR reader，避免重复初始化
_ocr_reader = None

def get_ocr_reader():
    """获取OCR reader，如果不存在则创建"""
    global _ocr_reader
    logger = get_logger()
    
    if _ocr_reader is None:
        logger.info("开始初始化EasyOCR模型")
        import easyocr
        
        # 在打包环境中设置模型路径
        model_path = setup_easyocr_model_path()
        
        # 如果在打包环境且没有网络，设置环境变量禁用下载
        if hasattr(sys, '_MEIPASS'):
            os.environ['EASYOCR_DISABLE_DOWNLOAD'] = '1'
        
        try:
            if model_path and os.path.exists(model_path):
                logger.info(f"使用本地EasyOCR模型: {model_path}")
                # 使用自定义模型目录，EasyOCR会优先使用本地模型
                _ocr_reader = easyocr.Reader(
                    ['ch_sim', 'en'], 
                    model_storage_directory=model_path,
                    verbose=False
                )
                logger.info("EasyOCR本地模型初始化成功")
            else:
                # 如果没有本地模型，尝试使用默认路径（仅限开发环境）
                logger.warning("未找到本地模型，尝试使用默认路径（可能需要网络连接）")
                if hasattr(sys, '_MEIPASS'):
                    # 在打包环境中，如果找不到模型就抛出错误
                    raise Exception("打包环境中未找到EasyOCR模型文件，请检查打包配置")
                else:
                    # 开发环境允许下载
                    _ocr_reader = easyocr.Reader(['ch_sim', 'en'], verbose=False)
                    logger.info("EasyOCR默认路径初始化成功")
                    
        except Exception as e:
            logger.error(f"EasyOCR初始化失败: {e}")
            
            # 如果是网络错误且在打包环境中，提供更详细的错误信息
            if hasattr(sys, '_MEIPASS') and ("urlopen error" in str(e) or "连接" in str(e)):
                error_msg = (
                    "EasyOCR模型初始化失败：无法连接网络下载模型。\n"
                    "这通常是因为程序无法找到打包的模型文件。\n"
                    "解决方案：\n"
                    "1. 确保程序运行目录有足够的权限\n"
                    "2. 重新下载最新版本的程序\n"
                    "3. 检查防火墙设置"
                )
                logger.error(error_msg)
                raise Exception(error_msg)
            
            # 其他情况下尝试重新初始化（仅限开发环境）
            if not hasattr(sys, '_MEIPASS'):
                try:
                    logger.info("尝试重新初始化EasyOCR（开发环境）")
                    _ocr_reader = easyocr.Reader(['ch_sim', 'en'], verbose=False)
                    logger.info("EasyOCR重新初始化成功")
                except Exception as e2:
                    logger.error(f"EasyOCR重新初始化也失败: {e2}")
                    raise e2
            else:
                # 在打包环境中直接抛出错误
                raise e
    
    return _ocr_reader

def get_display_width(text):
    """计算文本的显示宽度，中文字符算2个宽度，英文字符算1个宽度"""
    width = 0
    for char in text:
        if ord(char) > 127:  # 非ASCII字符（包括中文）
            width += 2
        else:
            width += 1
    return width

def format_price_result(item_name, price_info, max_width=24):
    """格式化价格显示结果，让冒号后的内容对齐"""
    item_width = get_display_width(item_name)
    # 计算需要的空格数来对齐，确保至少有1个空格
    spaces_needed = max(1, max_width - item_width)
    return f"{item_name}{'：' + ' ' * (spaces_needed - 1)}{price_info}"

def parse_guangzhou_price_string(price_str):
    """解析广州服务器价格字符串格式，如'10px4,13px3,14px2,15px1'转为'10p×4人, 13p×3人, 14p×2人, 15p×1人'"""
    if not price_str or not isinstance(price_str, str):
        return "无价格数据"
    
    try:
        # 按逗号分割每个价格项
        price_parts = price_str.split(',')
        formatted_prices = []
        
        for part in price_parts:
            part = part.strip()
            if 'px' in part:
                # 解析格式如 '10px4' -> '10p×4人'
                price, count = part.split('px')
                formatted_prices.append(f"{price}p×{count}人")
        
        return ', '.join(formatted_prices) if formatted_prices else "格式错误"
        
    except Exception as e:
        return f"解析错误: {price_str}"

def ocr_and_search_prices(ori_img, server_type='wm_api', file_lock=None, color_mode='golden'):
    """
    OCR识别图片中的物品并查询Warframe Market价格
    
    参数:
        ori_img: 输入图片路径或numpy数组
        server_type: 服务器类型，'wm_api' 或 'guangzhou'
        file_lock: 文件读写锁，用于广州服务器模式的并发安全
        color_mode: 颜色识别模式，'golden' 或 'all_colors'
        
    返回:
        list: 包含所有识别和搜索结果的列表
    """
    logger = get_logger()
    logger.info("=== 开始OCR识别和价格查询 ===")
    logger.info(f"服务器类型: {server_type}")
    logger.info(f"输入图片类型: {'文件路径' if isinstance(ori_img, str) else 'numpy数组'}")
    logger.info(f"颜色模式: {color_mode}")
    
    results = []
    
    # 加载原始图片
    if isinstance(ori_img, str):
        img = cv2.imread(ori_img)
        logger.info(f"从文件加载图片: {ori_img}")
    else:
        img = ori_img
        logger.info("使用传入的numpy数组图片")
        
    logger.info(f"原始图片尺寸: {img.shape}")
    
    # 根据颜色模式决定是否进行黄色提取
    if color_mode == 'golden':
        # ---- 步骤1：提取黄色文字，生成白底黄字图 ----
        logger.info("步骤1: 开始提取黄色文字")
        
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_yellow = np.array([20, 100, 150])
        upper_yellow = np.array([26, 255, 255])
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        logger.info("完成黄色区域检测")

        # 白底
        white_bg = np.ones_like(img) * 255
        result = cv2.bitwise_and(img, img, mask=mask)
        inv_mask = cv2.bitwise_not(mask)
        white_part = cv2.bitwise_and(white_bg, white_bg, mask=inv_mask)
        final = cv2.add(result, white_part)
        cv2.imwrite('yellow_on_white_ori.png', final)
        logger.info("完成黄色文字提取，已保存到 yellow_on_white_ori.png")
    else:
        # ---- 全部颜色模式：直接使用原图 ----
        logger.info("步骤1: 使用全部颜色模式，跳过黄色提取")
        final = img
        cv2.imwrite('yellow_on_white_ori.png', final)
        logger.info("原图已保存到 yellow_on_white_ori.png")

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
    logger.info("步骤3: 开始EasyOCR文字识别")
    reader = get_ocr_reader()  # 使用全局reader，避免重复初始化
    
    # 直接从处理后的图像进行OCR，避免文件读写
    if isinstance(ori_img, str):
        result = reader.readtext(ori_img, detail=1)
        logger.info(f"对原始文件进行OCR识别")
    else:
        # 如果是numpy数组，直接使用
        result = reader.readtext(final, detail=1)
        logger.info(f"对处理后的图像进行OCR识别")

    logger.info(f"OCR识别到 {len(result)} 个文本框")
    
    # 转结构化list
    items = []
    for i, (bbox, text, conf) in enumerate(result):
        x1 = int(bbox[0][0])
        x2 = int(bbox[2][0])
        if x1 > x2:
            x1, x2 = x2, x1
        items.append({'x1': x1, 'x2': x2, 'text': text, 'merged': False})
        logger.debug(f"识别文本 {i+1}: '{text}' (置信度: {conf:.3f}, 坐标: {x1}-{x2})")

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

    # ---- 查询本地price.json文件价格 ----
    def get_local_prices(item_en_name, file_lock=None):
        """从本地price.json文件查询价格"""
        logger = get_logger()
        logger.debug(f"查询本地价格: {item_en_name}")
        try:
            if not os.path.exists('price.json'):
                logger.warning("price.json文件不存在")
                return None
            
            # 使用文件锁确保读取安全
            if file_lock:
                with file_lock:
                    with open('price.json', 'r', encoding='utf-8') as f:
                        price_data = json.load(f)
                logger.debug("使用文件锁读取price.json")
            else:
                # 如果没有提供锁，直接读取（向后兼容）
                with open('price.json', 'r', encoding='utf-8') as f:
                    price_data = json.load(f)
                logger.debug("直接读取price.json")
            
            if 'data' in price_data and item_en_name in price_data['data']:
                price = price_data['data'][item_en_name]
                logger.debug(f"找到本地价格: {item_en_name} -> {price}")
                return price
            
            logger.debug(f"本地价格数据中未找到: {item_en_name}")
            return None
        except Exception as e:
            logger.error(f"读取本地价格文件出错: {e}")
            return None

    # ---- 查warframe market售价 ----
    def get_wfm_prices(item_en_name):
        logger = get_logger()
        logger.debug(f"查询WM API价格: {item_en_name}")
        url = f'https://api.warframe.market/v1/items/{item_en_name}/orders'
        headers = {
            'accept': 'application/json'
        }
        try:
            logger.debug(f"请求WM API: {url}")
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                logger.warning(f"WM API请求失败，状态码: {r.status_code}")
                return None
            
            data = r.json()
            if "payload" not in data or "orders" not in data["payload"]:
                logger.warning(f"WM API返回数据格式异常: {item_en_name}")
                return None
            
            # 只统计卖家且为在售状态
            all_orders = data["payload"]["orders"]
            orders = [o for o in all_orders if o["order_type"]=="sell" and o["user"]["status"]=="ingame"]
            logger.debug(f"找到 {len(orders)} 个有效卖单 (总共 {len(all_orders)} 个订单)")
            
            # 前10名
            orders = sorted(orders, key=lambda x: x['platinum'])[:10]
            price_counter = Counter([o['platinum'] for o in orders])
            logger.debug(f"WM API价格统计: {dict(price_counter)}")
            return price_counter
        except Exception as e:
            logger.error(f"查询WM API出错: {e}")
            return None

    # ---- 通用价格查询函数 ----
    def get_prices(item_en_name, server_type, file_lock=None):
        """根据服务器类型查询价格"""
        if server_type == 'guangzhou':
            local_price = get_local_prices(item_en_name, file_lock)
            if local_price:
                return local_price
            else:
                return None
        else:  # wm_api
            return get_wfm_prices(item_en_name)

    exact_found = []
    need_fuzzy = []
    
    logger.info(f"步骤4: 开始物品匹配和价格查询")
    logger.info(f"合并后的识别文本: {[item['text'] for item in items]}")
    
    for i, item in enumerate(items):
        zh = item['text']
        logger.debug(f"处理物品 {i+1}: '{zh}'")
        
        # 检查是否包含Forma关键字
        if 'Forma' in zh or 'forma' in zh.lower():
            logger.debug(f"检测到Forma物品，跳过查价: {zh}")
            results.append(format_price_result(zh, "未收录"))
            continue
        
        # 如果以'蓝'结尾，先加上'图'再匹配
        search_zh = zh
        if zh.endswith('蓝'):
            search_zh = zh + '图'
            logger.debug(f"物品名以'蓝'结尾，修正为: '{search_zh}'")
        
        en = find_en_by_cn(search_zh)
        logger.debug(f"中文名匹配结果: '{search_zh}' -> {en if en else '未找到'}")
        
        if en:
            # ---- 精确匹配查价 ----
            price_result = get_prices(en, server_type, file_lock)
            if price_result:
                if server_type == 'guangzhou':
                    # 本地JSON文件返回的是字符串，需要解析格式化
                    price_info = parse_guangzhou_price_string(price_result)
                else:
                    # WM API返回的是Counter对象
                    price_list = [f"{price}p×{count}人" for price, count in price_result.items()]
                    price_info = ', '.join(price_list)
                
                # 如果使用了修正后的名称，显示修正信息
                display_name = search_zh if search_zh != zh else zh
                results.append(format_price_result(display_name, price_info))
            else:
                # 如果使用了修正后的名称，显示修正信息
                display_name = search_zh if search_zh != zh else zh
                results.append(format_price_result(display_name, "无有效卖单"))
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
                    price_result = get_prices(en_fuzzy, server_type, file_lock)
                    if price_result:
                        if server_type == 'guangzhou':
                            price_info = parse_guangzhou_price_string(price_result)
                        else:
                            price_list = [f"{price}p×{count}人" for price, count in price_result.items()]
                            price_info = ', '.join(price_list)
                        results.append(f"  {format_price_result(zh_match, price_info)}")
                    else:
                        results.append(f"  {format_price_result(zh_match, '无有效卖单')}")
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
                        price_result = get_prices(en_fuzzy, server_type, file_lock)
                        if price_result:
                            if server_type == 'guangzhou':
                                price_info = parse_guangzhou_price_string(price_result)
                            else:
                                price_list = [f"{price}p×{count}人" for price, count in price_result.items()]
                                price_info = ', '.join(price_list)
                            results.append(f"  {format_price_result(zh_match, price_info)}")
                        else:
                            results.append(f"  {format_price_result(zh_match, '无有效卖单')}")
                else:
                    # 使用修正后的名称显示搜索结果
                    display_name = search_zh if search_zh != zh else zh
                    results.append(format_price_result(display_name, "无匹配结果"))
                    logger.debug(f"模糊搜索无结果: {display_name}")
    
    logger.info(f"=== OCR识别和价格查询完成 ===")
    logger.info(f"最终结果数量: {len(results)}")
    
    return results


# 为了保持向后兼容，如果直接运行此文件，使用默认参数
if __name__ == "__main__":
    results = ocr_and_search_prices('yellow_on_white_ori.png')
    for result in results:
        print(result)