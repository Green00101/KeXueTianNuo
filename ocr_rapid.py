# -*- coding: utf-8 -*-
"""
使用 RapidOCR（ONNX）的识别 + 查价流程，与 ocr.py 接口一致。
依赖: pip install rapidocr_onnxruntime
与 ocr.py 共用查价逻辑，仅 OCR 引擎不同。
"""
import cv2
import numpy as np
import os
import sys

from search_prices import search_prices_from_merged_items


def _preprocess_for_ocr(ori_img):
    """
    与 ocr.py 一致的预处理：放大、颜色掩码、黑字白底、CLAHE。
    返回预处理后的图像，失败返回 None。
    """
    if isinstance(ori_img, str):
        img = cv2.imread(ori_img)
    else:
        img = ori_img
    if img is None:
        return None

    h, w = img.shape[:2]
    scale = 2.0 if (h < 120 or max(w, h) < 500) else (1.5 if (h < 180 or max(w, h) < 800) else 1.0)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 5, 50, 50)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    gold_mask = cv2.inRange(hsv, np.array([5, 40, 90]), np.array([50, 255, 255]))
    white_mask = cv2.inRange(hsv, np.array([0, 0, 140]), np.array([180, 85, 255]))
    light_mask = cv2.inRange(hsv, np.array([0, 0, 115]), np.array([180, 95, 255]))
    mask = cv2.bitwise_or(cv2.bitwise_or(gold_mask, white_mask), light_mask)

    kernel_open = np.ones((2, 2), np.uint8)
    kernel_close = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        if cv2.contourArea(c) < 40:
            cv2.drawContours(mask, [c], -1, 0, -1)

    inv_gray = 255 - gray
    final = np.where(mask > 0, inv_gray, 255).astype(np.uint8)
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        final = clahe.apply(final)
    except Exception:
        pass
    return final


def _rapid_result_to_merged_items(rapid_result, img_height=400):
    """
    将 RapidOCR 的 result 转为与 EasyOCR 相同的 merged_items 格式。
    若某条识别结果 text 内含换行或连续空格，会拆成多行/多段，避免多行挤在一格展示。
    """
    if not rapid_result:
        return []

    def to_item(entry):
        if isinstance(entry, (list, tuple)):
            box, text, score = entry[0], entry[1], float(entry[2]) if len(entry) > 2 else 0.0
        else:
            box, text, score = entry.get('box'), entry.get('text', ''), float(entry.get('score', 0))
        bbox = np.array(box).reshape(-1, 2) if np.array(box).size >= 8 else box
        return (bbox.tolist() if hasattr(bbox, 'tolist') else bbox, (text or '').strip(), score)

    result = [to_item(e) for e in rapid_result]
    items = []
    for bbox, text, conf in result:
        t = (text or '').strip()
        if not t or t in ('|', '| ', ' |', '—', '-'):
            continue
        if conf < 0.2 and len(t) < 4:
            continue
        if len(t) <= 1 and conf < 0.5:
            continue
        pts = bbox if isinstance(bbox[0], (list, tuple)) else [bbox[:2], bbox[2:4]]
        y_center = (int(pts[0][1]) + int(pts[2][1] if len(pts) > 2 else pts[1][1])) // 2
        x1, x2 = int(pts[0][0]), int(pts[1][0]) if len(pts) > 1 else int(pts[0][0])
        if x1 > x2:
            x1, x2 = x2, x1
        # 若一条结果含换行或双空格，拆成多段，用虚拟 y_center 区分行
        parts = []
        for line in t.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            line = line.strip()
            if not line:
                continue
            for seg in (_s for _ in line.replace('\u3000', ' ').split('  ') if (_s := _.strip())):
                if seg:
                    parts.append(seg)
        if not parts:
            parts = [t]
        line_inc = max(20, img_height // 20)
        for i, seg in enumerate(parts):
            items.append({'x1': x1, 'x2': x2, 'y_center': y_center + i * line_inc, 'text': seg, 'conf': conf})

    line_threshold = max(10, min(18, img_height // 45))
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
        for item in sorted(line['items'], key=lambda x: x['x1']):
            t = (item['text'] or '').strip()
            if t:
                merged_items.append({'x1': item['x1'], 'x2': item['x2'], 'text': t, 'merged': True})
    return merged_items


def ocr_and_search_prices_rapid(ori_img, progress_callback=None):
    """
    使用 RapidOCR 识别图片中的物品并查价，接口与 ocr.ocr_and_search_prices 一致。
    ori_img: 图片路径或 numpy 数组
    progress_callback: 可选，查价前调用 progress_callback('searching')
    返回: list of str（每条查价结果一行）
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return ["未安装 rapidocr_onnxruntime，请执行: pip install rapidocr_onnxruntime"]

    final = _preprocess_for_ocr(ori_img)
    if final is None:
        return ["无法读取图片"]

    engine = RapidOCR()
    result_list, elapse = engine(final)
    if not result_list:
        return ["RapidOCR 未识别到文字"]
    merged_items = _rapid_result_to_merged_items(result_list, img_height=final.shape[0])
    if progress_callback:
        try:
            progress_callback('searching')
        except Exception:
            pass
    return search_prices_from_merged_items(merged_items)


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    path = sys.argv[1] if len(sys.argv) > 1 else "4.png"
    for line in ocr_and_search_prices_rapid(path):
        print(line)
