import os
import cv2
import uuid
import pathlib
from ultralytics import YOLO

class YoloDetector:
    def __init__(self, model_path, static_folder):
        self.model_path = model_path
        self.static_folder = static_folder
        self.results_folder = os.path.join(static_folder, 'results')
        self.crops_folder = os.path.join(static_folder, 'crops')
        
        os.makedirs(self.results_folder, exist_ok=True)
        os.makedirs(self.crops_folder, exist_ok=True)
        
        # 解决 Windows 路径问题
        if os.name == 'nt':
            pathlib.PosixPath = pathlib.WindowsPath
            
        print(f"[YOLO] 正在加载模型: {self.model_path}")
        try:
            self.model = YOLO(self.model_path)
            print("[YOLO] 模型加载成功!")
        except Exception as e:
            print(f"[YOLO] 模型加载失败: {e}")
            self.model = None

    def detect(self, image_path, conf_thres=0.25, iou_thres=0.45):
        if not self.model:
            raise Exception("YOLO 模型未加载")

        results = self.model(image_path, conf=conf_thres, iou=iou_thres)
        result = results[0]
        
        # 保存结果图
        filename = os.path.basename(image_path)
        result_filename = f"result_{filename}"
        result_path = os.path.join(self.results_folder, result_filename)
        
        annotated_frame = result.plot()
        cv2.imwrite(result_path, annotated_frame)
        
        detections = []
        original_img = cv2.imread(image_path)
        h, w, _ = original_img.shape
        
        # 解析检测框
        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        clss = result.boxes.cls.cpu().numpy()
        
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = map(int, box)
            
            # 裁剪图片供 OCR 使用 (加一点 padding)
            pad = 5
            cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
            cx2, cy2 = min(w, x2 + pad), min(h, y2 + pad)
            crop_img = original_img[cy1:cy2, cx1:cx2]
            
            crop_filename = f"crop_{uuid.uuid4().hex}.jpg"
            crop_path = os.path.join(self.crops_folder, crop_filename)
            cv2.imwrite(crop_path, crop_img)
            
            detections.append({
                'label': result.names[int(clss[i])],
                'conf': round(float(confs[i]), 2),
                'bbox': [x1, y1, x2, y2],
                'crop_path': crop_path
            })
            
        return {
            'image_url': f"results/{result_filename}", # 返回给前端的相对路径
            'detections': detections
        }