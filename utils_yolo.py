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
        
        if os.name == 'nt':
            pathlib.PosixPath = pathlib.WindowsPath
            
        # [静默模式] 注释掉加载日志
        # print(f"[YOLO] 正在加载模型: {self.model_path}")
        try:
            self.model = YOLO(self.model_path)
            # print("[YOLO] 模型加载成功!")
        except Exception as e:
            print(f"[YOLO ERROR] 模型加载失败: {e}")
            self.model = None

    def detect_frame(self, frame, conf_thres=0.5, iou_thres=0.45):
        if not self.model:
            return frame, []

        # [静默模式] 增加 verbose=False 防止 YOLO 打印推理日志
        results = self.model(frame, conf=conf_thres, iou=iou_thres, verbose=False)
        result = results[0]
        
        annotated_frame = result.plot()
        
        detections = []
        boxes = result.boxes.xyxy.cpu().numpy()
        clss = result.boxes.cls.cpu().numpy()
        names = result.names
        
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = map(int, box)
            detections.append({
                'label': names[int(clss[i])],
                'bbox': [x1, y1, x2, y2]
            })
            
        return annotated_frame, detections

    def detect(self, image_path, conf_thres=0.25, iou_thres=0.45):
        if not self.model:
            raise Exception("YOLO 模型未加载")

        # [静默模式] 增加 verbose=False
        results = self.model(image_path, conf=conf_thres, iou=iou_thres, verbose=False)
        result = results[0]
        
        filename = os.path.basename(image_path)
        result_filename = f"result_{filename}"
        result_path = os.path.join(self.results_folder, result_filename)
        
        annotated_frame = result.plot()
        cv2.imwrite(result_path, annotated_frame)
        
        detections = []
        original_img = cv2.imread(image_path)
        h, w, _ = original_img.shape
        
        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        clss = result.boxes.cls.cpu().numpy()
        
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = map(int, box)
            
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
            'image_url': f"results/{result_filename}",
            'detections': detections
        }