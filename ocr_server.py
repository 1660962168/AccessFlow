import os
import cv2
import numpy as np
import re
import logging
import threading
from flask import Flask, request, jsonify
from paddleocr import PaddleOCR

# --- 配置部分 ---
app = Flask(__name__)
# 减少 Paddle 的红字日志干扰
logging.getLogger("ppocr").setLevel(logging.ERROR)

# 全局变量
ocr_model = None
lock = threading.Lock()

def init_model():
    global ocr_model
    print("[OCR Server] 正在初始化 PaddleOCR 模型...")
    try:
        ocr_model = PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_recognition_model_name="PP-OCRv5_server_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="gpu",  # 如果报错提示没有 GPU，请改为 "cpu"
            lang="cn"
        )
        print("[OCR Server] ✅ 模型加载完成，服务运行在端口 5001")
    except Exception as e:
        print(f"[OCR Server FATAL] 模型初始化失败: {e}")

def process_text_score(text, score):
    """辅助函数：清洗文本并转换分数"""
    try:
        score_val = float(score)
    except:
        score_val = 0.0
    
    # 清洗：只保留汉字、大写字母、数字
    clean_text = re.sub(r'[^\u4e00-\u9fa5A-Z0-9]', '', str(text))
    
    # 过滤：车牌通常大于4位
    if len(clean_text) < 4:
        return None, 0.0
    
    return clean_text, round(score_val, 2)

@app.route('/ocr', methods=['POST'])
def ocr_predict():
    if not ocr_model:
        return jsonify({'error': 'Model not ready'}), 503

    data = request.json
    image_path = data.get('path')

    if not image_path:
        return jsonify({'error': 'Path required'}), 400

    try:
        # print(f"[OCR Server] 请求文件: {image_path}") # 调试用

        # --- 1. 读取图片 (解决中文路径问题) ---
        if not os.path.exists(image_path):
             print(f"[OCR Server] ❌ 文件不存在: {image_path}")
             return jsonify({'error': 'File not found'}), 404

        # 使用 numpy + imdecode 读取，完美避开 Windows 中文路径 bug
        img_array = np.fromfile(image_path, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None:
             print("[OCR Server] ❌ 图片解码失败")
             return jsonify({'error': 'Decode failed'}), 500

        # --- 2. 模型推理 ---
        with lock:
            results = ocr_model.predict(img)

        # --- 3. 解析结果 (兼容字典和列表) ---
        best_res = None
        best_score = -1
        
        # 调试打印，如果还有问题可以打开这个看
        # print(f"[DEBUG] Raw Results: {results}")

        if isinstance(results, list) and len(results) > 0:
            data_item = results[0]
            
            # 【情况 A】: 字典格式 (你遇到的情况: {'rec_texts': [], ...})
            if isinstance(data_item, dict) and 'rec_texts' in data_item:
                texts = data_item.get('rec_texts', [])
                scores = data_item.get('rec_scores', [])
                
                for text, score in zip(texts, scores):
                    txt, conf = process_text_score(text, score)
                    if txt and conf > best_score:
                        best_score = conf
                        best_res = {'text': txt, 'conf': conf}

            # 【情况 B】: 列表格式 (旧版格式: [[box, (text, score)], ...])
            elif isinstance(data_item, list):
                for line in data_item:
                    # line 通常是 [box, (text, score)]
                    if len(line) == 2 and isinstance(line[1], (list, tuple)):
                        text, score = line[1]
                        txt, conf = process_text_score(text, score)
                        if txt and conf > best_score:
                            best_score = conf
                            best_res = {'text': txt, 'conf': conf}

        # --- 4. 返回结果 ---
        if best_res:
            print(f"[OCR Server] 🎯 识别成功: {best_res['text']} (Conf: {best_res['conf']})")
        else:
            print(f"[OCR Server] ⚠️ 未识别到有效内容")

        return jsonify({'success': True, 'data': best_res})

    except Exception as e:
        print(f"[OCR Server Error] 处理异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    init_model()
    # threaded=True 允许并发处理
    app.run(host='0.0.0.0', port=5001, threaded=True)