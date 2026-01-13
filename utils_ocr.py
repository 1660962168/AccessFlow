import os
import cv2
import threading
import re
from paddleocr import PaddleOCR

# 屏蔽 Paddle 联网检查
# os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'

class OcrDetector:
    def __init__(self):
        self.ocr = None
        self.is_ready = False
        self.lock = threading.Lock()
        
        # 后台线程加载，不阻塞主程序
        t = threading.Thread(target=self._init_model)
        t.daemon = True
        t.start()
        
    def _init_model(self):
        print("[OCR] 正在后台初始化 PaddleOCR...")
        try:
            self.ocr = PaddleOCR(
                text_detection_model_name="PP-OCRv5_server_det",
                text_recognition_model_name="PP-OCRv5_server_rec",
                use_angle_cls=False, 
                lang="ch"
            )
            with self.lock:
                self.is_ready = True
            print("[OCR] 初始化完成")
        except Exception as e:
            print(f"[OCR] 初始化失败: {e}")

    def recognize(self, image_path):
        if not self.is_ready:
            return None
            
        img = cv2.imread(image_path)
        if img is None: return None

        # 图像预处理 (放大+反色尝试，提高识别率)
        roi = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray_inv = cv2.bitwise_not(gray)
        gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        gray_inv_bgr = cv2.cvtColor(gray_inv, cv2.COLOR_GRAY2BGR)

        best_res = None
        best_score = -1

        for input_img in [gray_bgr, gray_inv_bgr]:
            try:
                res = self.ocr.ocr(input_img, cls=False, det=True, rec=True)
                if not res or not res[0]: continue
                
                for line in res[0]:
                    text, score = line[1]
                    # 简单清洗
                    clean_text = re.sub(r'[^\u4e00-\u9fa5A-Z0-9]', '', text)
                    if len(clean_text) < 2: continue
                    
                    if score > best_score:
                        best_score = score
                        best_res = {'text': clean_text, 'conf': round(float(score), 2)}
            except:
                pass
                
        return best_res