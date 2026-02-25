import cv2
import numpy as np
import sys
import os

import easyocr


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


from search_prices import search_prices_from_merged_items


def ocr_and_search_prices(ori_img, progress_callback=None):
    """
    OCR识别图片中的物品并查询Warframe Market价格
    
    参数:
        ori_img: 输入图片路径或numpy数组
        progress_callback: 可选，阶段切换时调用 progress_callback('searching')（OCR 完成后、查价前）
        
    返回:
        list: 包含所有识别和搜索结果的列表
    """
    results = []
    # ---- 步骤1：提取文字（金/白/浅色），生成高对比度图供 OCR ----
    if isinstance(ori_img, str):
        img = cv2.imread(ori_img)
    else:
        img = ori_img
    if img is None:
        return ["无法读取图片"]

    # 小图或扁条图放大，提升小字/多行识别率
    h, w = img.shape[:2]
    scale = 1.0
    if h < 120 or max(w, h) < 500:
        scale = 2.0
    elif h < 180 or max(w, h) < 800:
        scale = 1.5
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 轻度双边滤波，压背景噪点、保留文字边缘
    gray = cv2.bilateralFilter(gray, 5, 50, 50)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 金色（选中态）：黄-橙-金
    lower_gold = np.array([5, 40, 90])
    upper_gold = np.array([50, 255, 255])
    gold_mask = cv2.inRange(hsv, lower_gold, upper_gold)

    # 白色/高亮（未选中态）
    lower_white = np.array([0, 0, 140])
    upper_white = np.array([180, 85, 255])
    white_mask = cv2.inRange(hsv, lower_white, upper_white)

    # 浅色文字（未选中偏灰白/米色，real 等图）
    lower_light = np.array([0, 0, 115])
    upper_light = np.array([180, 95, 255])
    light_mask = cv2.inRange(hsv, lower_light, upper_light)

    mask = cv2.bitwise_or(gold_mask, white_mask)
    mask = cv2.bitwise_or(mask, light_mask)
    # 形态学：先开运算去小噪点，再闭运算连通笔画
    kernel_open = np.ones((2, 2), np.uint8)
    kernel_close = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
    # 去掉小连通域（噪点、图标碎片）；多行/复杂图适当提高以去图标
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = 40
    for c in contours:
        if cv2.contourArea(c) < min_area:
            cv2.drawContours(mask, [c], -1, 0, -1)
    # 生成高对比度图：掩码区域内为“黑字”（原图亮→反相为暗），区域外白底，便于 OCR
    inv_gray = 255 - gray
    final = np.where(mask > 0, inv_gray, 255).astype(np.uint8)
    # 可选：对整图做 CLAHE 提升对比度
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        final = clahe.apply(final)
    except Exception:
        pass
    # 水平投影检测多行带区，分带 OCR 减轻行间重叠与干扰（单行也走分带逻辑，便于统一处理）
    def _horizontal_bands(mask_img, min_gap=4, min_height=4, pad=6):
        proj = np.sum(mask_img > 0, axis=1).astype(np.float32)
        if proj.max() <= 0:
            return None
        kernel = np.ones(5, np.float32) / 5
        proj = np.convolve(proj, kernel, mode='same')
        thresh = max(1, 0.08 * proj.max())  # 略降阈值，多行时更容易拆出带
        rows = np.where(proj >= thresh)[0]
        if len(rows) < min_height:
            return None
        gaps = np.diff(rows)
        gap_idx = np.where(gaps > min_gap)[0]
        starts = [rows[0]]
        ends = []
        for i in gap_idx:
            ends.append(rows[i] + 1)
            starts.append(rows[i + 1])
        ends.append(rows[-1] + 1)
        bands = []
        for s, e in zip(starts, ends):
            if e - s >= min_height:
                bands.append((max(0, s - pad), min(mask_img.shape[0], e + pad)))
        return bands if len(bands) >= 1 else None

    bands = _horizontal_bands(mask)
    use_band_ocr = bands is not None
    # ---- 步骤2：EasyOCR 识别（整图或分带） ----
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

    reader = get_ocr_reader()
    ocr_kw = dict(
        detail=1, batch_size=1, workers=1, paragraph=False,
        text_threshold=0.35, low_text=0.25, contrast_ths=0.1,
        adjust_contrast=0.3, min_size=6, decoder='greedy'
    )

    if use_band_ocr and bands is not None:
        result = []
        for i, (r0, r1) in enumerate(bands):
            strip = final[r0:r1, :]
            if strip.size == 0:
                continue
            part = reader.readtext(strip, **ocr_kw)
            for bbox, text, conf in part:
                # 将条带内坐标还原到整图
                adj = [[p[0], p[1] + r0] for p in bbox]
                result.append((adj, text, conf))
    else:
        result = reader.readtext(final, **ocr_kw)
    # 转结构化 list，过滤明显无效结果（分隔符、极低置信度噪点）
    items = []
    for bbox, text, conf in result:
        t = (text or '').strip()
        if not t or t in ('|', '| ', ' |', '—', '-'):
            continue
        if conf < 0.2 and len(t) < 4:  # 短且置信度极低多为噪点
            continue
        if len(t) <= 1 and conf < 0.5:
            continue
        y_center = (int(bbox[0][1]) + int(bbox[2][1])) // 2
        x1 = int(bbox[0][0])
        x2 = int(bbox[2][0])
        if x1 > x2:
            x1, x2 = x2, x1
        items.append({'x1': x1, 'x2': x2, 'y_center': y_center, 'text': text, 'conf': conf, 'merged': False})

    # 按行分组，同行内再按 X 间距拆成多个物品（避免整行合并成一条）
    # 自适应行距：图越高多行越多，用更严的行距避免不同行被合并
    line_threshold = max(8, min(14, h // 55))
    x_gap_threshold = 20  # 两段文字 X 间距大于此视为不同物品
    lines = []
    for item in items:
        added = False
        for line in lines:
            if abs(item['y_center'] - line['y_center']) <= line_threshold:
                line['items'].append(item)
                line['y_center'] = (line['y_center'] * len(line['items']) + item['y_center']) // (len(line['items']) + 1)
                added = True
                break
        if not added:
            lines.append({'y_center': item['y_center'], 'items': [item]})

    merged_items = []
    for line in lines:
        sorted_items = sorted(line['items'], key=lambda x: x['x1'])
        for item in sorted_items:
            t = (item['text'] or '').strip()
            if not t:
                continue
            merged_items.append({'x1': item['x1'], 'x2': item['x2'], 'text': t, 'merged': True})

    if progress_callback:
        try:
            progress_callback('searching')
        except Exception:
            pass
    return search_prices_from_merged_items(merged_items)


# 为了保持向后兼容，如果直接运行此文件，使用默认参数
if __name__ == "__main__":
    results = ocr_and_search_prices('yellow_on_white_ori.png')
    for result in results:
        print(result)