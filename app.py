from flask import Flask, session, render_template, jsonify, request, redirect, url_for, flash, send_file, Response
import config
from exts import db
from models import *
from flask_migrate import Migrate
from flask_apscheduler import APScheduler
import os
import cv2
import time
import threading
import re
import numpy as np
from werkzeug.utils import secure_filename
from datetime import datetime
from sqlalchemy import func  # 引入 func 用于 SQL 聚合查询

# 引入你的工具类
from utils_ocr import OcrDetector
from utils_yolo import YoloDetector


app = Flask(__name__)
app.config.from_object(config)
db.init_app(app)
migrate = Migrate(app, db)
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# --- 路径与模型初始化 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
UPLOAD_FOLDER = os.path.join(STATIC_FOLDER, 'uploads')
TEMP_FOLDER = os.path.join(STATIC_FOLDER, 'temp')
WEIGHTS_PATH = os.path.join(BASE_DIR, 'weights', 'best.pt')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

yolo_detector = YoloDetector(WEIGHTS_PATH, STATIC_FOLDER)
ocr_detector = OcrDetector()

# --- 全局状态 ---
camera_ocr_results = {}
camera_threads = {}
thread_start_lock = threading.Lock()

# 车牌校验正则
PLATE_PATTERN = re.compile(
    r'^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵青藏川宁琼港澳]{1}[A-Z]{1}[A-HJ-NP-Z0-9]{4}[A-HJ-NP-Z0-9挂学警港澳]{1}$|'
    r'^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵青藏川宁琼]{1}[A-Z]{1}[A-HJ-NP-Z0-9]{6}$|'
    r'^WJ[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵青藏川宁琼]{1}[0-9]{5}$|'
    r'^使[0-9]{3}[A-Z]{1}$|'
    r'^粤Z[A-HJ-NP-Z0-9]{4,5}(港|澳)?$'
)

class CameraThread(threading.Thread):
    def __init__(self, cam_id, rtsp_url, app):
        super().__init__()
        self.cam_id = cam_id
        self.rtsp_url = rtsp_url
        self.app = app
        self.running = True
        self.latest_frame = None
        self.lock = threading.Lock()
        self.daemon = True
        self.cached_detections = [] 
        
        self.cam_type = 'entrance'
        self.processed_plates = {} # 内存防抖缓存

    def is_valid_plate(self, plate_text):
        if not plate_text: return False
        return PLATE_PATTERN.match(plate_text) is not None

    # --- [新增] 更新车位的方法 ---
    def update_slots(self, change):
        """
        更新 SystemConfig 中的 available_slots
        change: -1 (车辆入库，车位减1)
        change: +1 (车辆出库，车位加1)
        注意：此方法必须在 save_record 的 db.session 上下文中调用
        """
        try:
            sys_conf = SystemConfig.query.first()
            if not sys_conf:
                # 如果配置表为空，创建一个默认的
                sys_conf = SystemConfig()
                db.session.add(sys_conf)
            
            # 更新数值
            sys_conf.available_slots += change
            
            # 边界检查：防止变成负数或超过总数
            if sys_conf.available_slots < 0:
                sys_conf.available_slots = 0
            if sys_conf.available_slots > sys_conf.parking_slots:
                sys_conf.available_slots = sys_conf.parking_slots
                
            print(f"[System] 车位变更: {change} -> 剩余: {sys_conf.available_slots}")
        except Exception as e:
            print(f"[System Error] 更新车位失败: {e}")

    def save_record(self, plate_text, plate_type):
        """数据库记录逻辑（包含车位更新）"""
        
        # 1. 正则校验
        if not self.is_valid_plate(plate_text):
            return

        now = datetime.now()
        
        # 2. 内存防抖 (30秒)
        last_time = self.processed_plates.get(plate_text)
        if last_time and (now - last_time).total_seconds() < 30:
            return

        # 更新内存缓存
        self.processed_plates[plate_text] = now

        with self.app.app_context():
            try:
                if self.cam_type == 'entrance':
                    # --- 入场逻辑 ---
                    
                    # 3. 数据库防抖
                    latest_record = ParkingRecord.query.filter_by(plate_number=plate_text)\
                        .order_by(ParkingRecord.entry_time.desc()).first()
                    
                    if latest_record and (now - latest_record.entry_time).total_seconds() < 30:
                        return

                    # 写入新记录
                    record = ParkingRecord(
                        plate_number=plate_text,
                        plate_type=plate_type,
                        entry_time=now,
                        status='入场'
                    )
                    db.session.add(record)
                    
                    # [关键修改] 入场成功 -> 车位 -1
                    self.update_slots(-1)
                    
                    print(f"[DB] ✅ 车辆入场: {plate_text} (车位-1)")
                    
                elif self.cam_type == 'exit':
                    # --- 出场逻辑 ---
                    
                    # 查找正在“入场”状态的记录
                    record = ParkingRecord.query.filter_by(
                        plate_number=plate_text, 
                        status='入场'
                    ).order_by(ParkingRecord.entry_time.desc()).first()
                    
                    if record:
                        record.exit_time = now
                        record.status = '出场'
                        
                        # [关键修改] 出场成功 -> 车位 +1
                        self.update_slots(+1)
                        
                        print(f"[DB] 👋 车辆出场: {plate_text} (车位+1)")
                    else:
                        # 没有入场记录，不操作
                        return

                # 统一提交：记录写入和车位更新在同一个事务里
                db.session.commit()
                
            except Exception as e:
                db.session.rollback()
                print(f"[DB Error] 写入失败: {e}")
                self.processed_plates.pop(plate_text, None)

    def run(self):
        cap = cv2.VideoCapture(self.rtsp_url)
        frame_count = 0
        DETECT_INTERVAL = 10  
        
        with self.app.app_context():
            cam_info = db.session.get(Camera, self.cam_id)
            if cam_info:
                self.cam_type = cam_info.cam_type
                print(f"[Camera {self.cam_id}] 类型: {self.cam_type}")
            
            sys_conf = SystemConfig.query.first()
            conf_thres = sys_conf.conf_thres if sys_conf else 0.5
            iou_thres = sys_conf.iou_thres if sys_conf else 0.45

        while self.running:
            success, frame = cap.read()
            if not success:
                time.sleep(2)
                try:
                    cap.release()
                    cap = cv2.VideoCapture(self.rtsp_url)
                except:
                    pass
                continue
            
            frame_count += 1
            final_frame = frame
            
            try:
                if frame_count % DETECT_INTERVAL == 0:
                    annotated_frame, detections = yolo_detector.detect_frame(frame, conf_thres, iou_thres)
                    self.cached_detections = detections 
                    final_frame = annotated_frame
                    
                    if detections and ocr_detector.is_ready:
                        det = detections[0]
                        plate_type = det.get('label', 'unknown') 

                        x1, y1, x2, y2 = det['bbox']
                        h, w, _ = frame.shape
                        pad = 5
                        cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
                        cx2, cy2 = min(w, x2 + pad), min(h, y2 + pad)
                        
                        crop_img = frame[cy1:cy2, cx1:cx2]
                        res = ocr_detector.recognize_temp_frame(crop_img, TEMP_FOLDER)
                        
                        if res:
                            text = res['text']
                            conf = res['conf']
                            
                            camera_ocr_results[self.cam_id] = {
                                'plate': text,
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'conf': conf,
                                'type': plate_type
                            }
                            
                            self.save_record(text, plate_type)

                else:
                    final_frame = frame.copy()
                    if self.cached_detections:
                        for det in self.cached_detections:
                            x1, y1, x2, y2 = det['bbox']
                            label = det['label']
                            cv2.rectangle(final_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(final_frame, label, (x1, y1 - 10), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

                ret, buffer = cv2.imencode('.jpg', final_frame)
                if ret:
                    with self.lock:
                        self.latest_frame = buffer.tobytes()
            
            except Exception:
                pass 

            time.sleep(0.015)
        
        cap.release()

    def get_frame(self):
        with self.lock:
            return self.latest_frame

    def stop(self):
        self.running = False

# --- 辅助函数 ---

def start_camera_thread(cam_id, rtsp_url):
    with thread_start_lock:
        if cam_id not in camera_threads:
            print(f"启动摄像头线程: {cam_id}")
            t = CameraThread(cam_id, rtsp_url, app)
            t.start()
            camera_threads[cam_id] = t
        else:
            if not camera_threads[cam_id].is_alive():
                print(f"重启摄像头线程: {cam_id}")
                t = CameraThread(cam_id, rtsp_url, app)
                t.start()
                camera_threads[cam_id] = t

def stop_camera_thread(cam_id):
    if cam_id in camera_threads:
        camera_threads[cam_id].stop()
        del camera_threads[cam_id]

# --- 路由 ---

@app.route('/video_feed/<int:cam_id>')
def video_feed(cam_id):
    cam = db.session.get(Camera, cam_id)
    if not cam:
        return "Camera not found", 404

    start_camera_thread(cam.id, cam.rtsp_url)

    def generate(cid):
        blank_img = np.zeros((480, 640, 3), np.uint8)
        cv2.putText(blank_img, "CONNECTING...", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        _, blank_encoded = cv2.imencode('.jpg', blank_img)
        blank_bytes = blank_encoded.tobytes()

        while True:
            thread = camera_threads.get(cid)
            frame_bytes = None
            if thread:
                frame_bytes = thread.get_frame()
            
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                time.sleep(0.05) 
            else:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + blank_bytes + b'\r\n')
                time.sleep(0.5)

    return Response(generate(cam.id), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/monitor/data')
def monitor_data():
    return jsonify(camera_ocr_results)

# --- 主页路由 (更新版) ---
@app.route('/')
def index():
    # 1. 获取系统配置
    sys_conf = SystemConfig.query.first()
    if not sys_conf:
        sys_conf = SystemConfig()
        db.session.add(sys_conf)
        db.session.commit()
    
    # 2. 自动校准剩余车位 (防止数据库车位计数跑偏)
    # 剩余车位 = 总车位 - 当前还在场内的车(status='入场')
    current_parked_count = ParkingRecord.query.filter_by(status='入场').count()
    sys_conf.available_slots = max(0, sys_conf.parking_slots - current_parked_count)
    
    # 3. 统计今日入场
    today = datetime.now().date()
    today_count = ParkingRecord.query.filter(func.date(ParkingRecord.entry_time) == today).count()
    
    db.session.commit()

    # 4. 获取最新10条记录 (混合入场和出场时间排序)
    records = ParkingRecord.query.order_by(
        func.coalesce(ParkingRecord.exit_time, ParkingRecord.entry_time).desc()
    ).limit(10).all()

    return render_template('index.html', 
                           config=sys_conf, 
                           today_count=today_count, 
                           records=records)

@app.route('/monitor')
def monitor():
    cameras = Camera.query.all()
    for cam in cameras:
        start_camera_thread(cam.id, cam.rtsp_url)
    return render_template('monitor.html', cameras=cameras)

@app.route('/camera/add', methods=['POST'])
def add_camera():
    name = request.form.get('name')
    rtsp_url = request.form.get('rtsp_url')
    cam_type = request.form.get('cam_type')
    if name and rtsp_url:
        new_cam = Camera(name=name, rtsp_url=rtsp_url, cam_type=cam_type)
        db.session.add(new_cam)
        db.session.commit()
        start_camera_thread(new_cam.id, new_cam.rtsp_url)
        flash('摄像头添加成功', 'success')
    else:
        flash('请填写完整信息', 'warning')
    return redirect(url_for('system_config'))

@app.route('/camera/delete/<int:cam_id>')
def delete_camera(cam_id):
    cam = db.session.get(Camera, cam_id)
    if cam:
        stop_camera_thread(cam_id)
        db.session.delete(cam)
        db.session.commit()
        flash('摄像头已删除', 'success')
    return redirect(url_for('system_config'))

@app.route('/config', methods=['GET', 'POST'])
def system_config():
    config_item = SystemConfig.query.first()
    if not config_item:
        config_item = SystemConfig()
        db.session.add(config_item)
        db.session.commit()
    cameras = Camera.query.order_by(Camera.created_at.desc()).all()
    if request.method == 'POST':
        try:
            config_item.conf_thres = float(request.form.get('conf_thres'))
            config_item.iou_thres = float(request.form.get('iou_thres'))
            config_item.use_ocr = True if request.form.get('use_ocr') == 'on' else False
            config_item.retention_days = int(request.form.get('retention_days'))
            # [新增] 允许修改总车位
            if request.form.get('parking_slots'):
                config_item.parking_slots = int(request.form.get('parking_slots'))
                
            db.session.commit()
            flash('全局参数配置已更新', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')
        return redirect(url_for('system_config'))
    return render_template('config.html', config=config_item, cameras=cameras)

@app.route('/recognition', methods=['GET', 'POST'])
def recognition():
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '未找到上传文件'})
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': '文件名为空'})

        try:
            filename = secure_filename(f"{int(time.time())}_{file.filename}")
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(save_path)

            conf_thres = float(request.form.get('conf_thres', 0.5))
            iou_thres = float(request.form.get('iou_thres', 0.45))
            use_ocr = request.form.get('use_ocr') == 'on'

            start_time = time.time()
            yolo_result = yolo_detector.detect(save_path, conf_thres, iou_thres)
            
            ocr_data = []
            if use_ocr and yolo_result['detections']:
                if ocr_detector.is_ready:
                    for det in yolo_result['detections']:
                        crop_path = det['crop_path']
                        if os.path.exists(crop_path):
                            ocr_res = ocr_detector.recognize(crop_path)
                            if ocr_res:
                                ocr_data.append({
                                    'text': ocr_res['text'],
                                    'conf': ocr_res['conf'],
                                    'type': det['label']
                                })
            
            time_elapsed = round(time.time() - start_time, 3)
            if os.path.exists(save_path): os.remove(save_path)
            for det in yolo_result['detections']:
                crop_path = det['crop_path']
                if os.path.exists(crop_path): os.remove(crop_path)

            return jsonify({
                'success': True,
                'image_url': url_for('static', filename=yolo_result['image_url'].replace('\\', '/')),
                'time_elapsed': time_elapsed,
                'results': yolo_result['detections'],
                'ocr_data': ocr_data
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    return render_template('recognition.html')

@app.route('/records')
def records():
    keyword = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    
    query = ParkingRecord.query.order_by(ParkingRecord.entry_time.desc())
    
    if keyword:
        query = query.filter(ParkingRecord.plate_number.like(f'%{keyword}%'))
    
    pagination = query.paginate(page=page, per_page=15)
    
    return render_template('records.html', 
                         pagination=pagination, 
                         records=pagination.items,
                         keyword=keyword)

@app.route('/record/delete/<int:record_id>', methods=['POST'])
def delete_record(record_id):
    try:
        record = db.session.get(ParkingRecord, record_id)
        if record:
            db.session.delete(record)
            db.session.commit()
            return jsonify({'success': True, 'message': '删除成功'})
        else:
            return jsonify({'success': False, 'message': '记录不存在'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/password', methods=['GET','POST'])
def password():
    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        user = User.query.filter_by(username=session.get('username')).first()
        if new_password!= confirm_password:
            flash('两次输入的密码不一致', 'warning')
            return render_template('password.html')
        if user and user.check_password(old_password):
            user.set_password(new_password)  
            db.session.commit()
            flash('密码修改成功','success')
            return redirect(url_for('password'))
        else:
            flash('旧密码错误', 'danger')
    return render_template('password.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            flash('请输入账号和密码', 'warning')
            return render_template('login.html')
        user = User.query.filter_by(username=username).first()
        if not user:
            flash('账号不存在，请检查用户名', 'danger')
        elif not user.check_password(password):
            flash('密码错误，请重新输入', 'danger') 
        else:
            session['username'] = username
            flash('登录成功，欢迎回来', 'success')
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('退出登录成功','success')
    return redirect(url_for('login'))

def init_data():
    with app.app_context():
        # 注意：如果修改了models表结构，可能需要删库重建或使用migrate
        db.create_all() 
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            new_admin = User(username='admin')
            new_admin.set_password('admin')
            db.session.add(new_admin)
            db.session.commit()
        
        cameras = Camera.query.all()
        for cam in cameras:
            start_camera_thread(cam.id, cam.rtsp_url)

if __name__ == '__main__':
    if os.environ.get('WERKZEUG_RUN_MAIN') or not app.debug:
        init_data()
    else:
        init_data()
        
    app.run(debug=True, host='0.0.0.0', threaded=True)