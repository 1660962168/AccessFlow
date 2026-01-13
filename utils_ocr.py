import os
import threading
import re
import numpy as np
from paddleocr import PaddleOCR

class OcrDetector:
    def __init__(self):
        self.ocr = None
        self.is_ready = False
        self.lock = threading.Lock()
        
        # 后台线程初始化，防止阻塞 Flask 启动
        t = threading.Thread(target=self._init_model)
        t.daemon = True
        t.start()
        
    def _init_model(self):
        print("[OCR] 正在后台初始化 PaddleOCR (配置: PP-OCRv5 / GPU)...")
        try:
            # --- 完全依照你的成功示例配置 ---
            self.ocr = PaddleOCR(
                text_detection_model_name="PP-OCRv5_server_det",
                text_recognition_model_name="PP-OCRv5_server_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device="gpu", 
                lang="cn" 
            )
            with self.lock:
                self.is_ready = True
            print("[OCR] 初始化完成")
        except Exception as e:
            print(f"[OCR] 初始化失败: {e}")
            import traceback
            traceback.print_exc()

    def recognize(self, image_path):
        # 1. 检查状态
        if not self.is_ready:
            print("[OCR DEBUG] 模型尚未就绪")
            return None
            
        if not os.path.exists(image_path):
            print(f"[OCR DEBUG] 找不到图片: {image_path}")
            return None

        # print(f"--- [OCR DEBUG] 开始识别: {os.path.basename(image_path)} ---")

        try:
            # 2. 执行预测
            results = self.ocr.predict(image_path)
            
            best_res = None
            best_score = -1

            # 3. 智能解析结果
            for res in results:
                data = None
                
                # --- 核心修改：兼容多种返回结构 ---
                
                # 尝试一：res 本身就是字典，且包含 'rec_texts' (直接数据)
                # 你的报错暗示很可能是这种情况：res 就是数据本身，没有外层的 'res' key
                if isinstance(res, dict) and 'rec_texts' in res:
                    data = res
                    
                # 尝试二：res 是字典，且包含 'res' key (嵌套数据)
                elif isinstance(res, dict) and 'res' in res:
                    data = res['res']
                
                # 尝试三：res 是对象，且有 .res 属性
                elif hasattr(res, 'res'):
                    data = res.res
                
                # 尝试四：res 是对象，支持下标访问 (如 PaddleX Result 对象)
                elif hasattr(res, '__getitem__'):
                    try:
                        # 看看能不能取到 'res'
                        data = res['res']
                    except KeyError:
                        # 如果没有 'res' 键，那它自己可能就是数据，检查有没有 'rec_texts'
                        try:
                            if res['rec_texts'] is not None:
                                data = res
                        except:
                            pass
                
                # 如果都没找到
                if data is None:
                    # 打印一下它的 keys 方便最后排查
                    keys_info = list(res.keys()) if isinstance(res, dict) else "Not a dict"
                    print(f"  > [解析跳过] 无法识别的数据结构，Available keys: {keys_info}")
                    continue

                # 4. 提取文本
                # PaddleX 可能返回 numpy array 或 list，这里做兼容处理
                rec_texts = data.get('rec_texts', [])
                rec_scores = data.get('rec_scores', [])

                if not rec_texts:
                    # print("  > 未检测到文本区域")
                    continue

                for text, score in zip(rec_texts, rec_scores):
                    # 转换分数为 float
                    try:
                        score_val = float(score)
                    except:
                        score_val = 0.0
                    
                    # 正则清洗：只留中文、英文、数字
                    clean_text = re.sub(r'[^\u4e00-\u9fa5A-Z0-9]', '', str(text))
                    
                    # print(f"    - 识别文本: '{text}' ({score_val:.2f}) -> '{clean_text}'")

                    if len(clean_text) < 2: continue
                    
                    if score_val > best_score:
                        best_score = score_val
                        best_res = {'text': clean_text, 'conf': round(score_val, 2)}

            if best_res:
                print(f"--- [OCR DEBUG] 识别结果: {best_res['text']} ---")
            else:
                pass
                # print("--- [OCR DEBUG] 无有效结果 ---")
                
            return best_res

        except Exception as e:
            print(f"[OCR] 执行异常: {e}")
            import traceback
            traceback.print_exc()
            return None