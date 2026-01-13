from flask import Flask, session, render_template, jsonify, request, redirect, url_for, flash, send_file
import config
from exts import db
from models import *
from flask_migrate import Migrate
from flask_apscheduler import APScheduler
import os
import cv2
import time
import numpy as np
from werkzeug.utils import secure_filename

# 引入你的工具类
from utils_yolo import YoloDetector
from utils_ocr import OcrDetector

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
WEIGHTS_PATH = os.path.join(BASE_DIR, 'weights', 'best.pt')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 1. 全局实例化模型 (OCR会自动在后台线程加载)
# 注意：YoloDetector 需要传递 weights 路径和 static 文件夹路径
yolo_detector = YoloDetector(WEIGHTS_PATH, STATIC_FOLDER)
ocr_detector = OcrDetector()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/recognition', methods=['GET', 'POST'])
def recognition():
    if request.method == 'POST':
        # 1. 检查文件
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '未找到上传文件'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': '文件名为空'})

        try:
            # 2. 保存文件
            filename = secure_filename(f"{int(time.time())}_{file.filename}")
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(save_path)

            # 3. 获取参数
            conf_thres = float(request.form.get('conf_thres', 0.5))
            iou_thres = float(request.form.get('iou_thres', 0.45))
            use_ocr = request.form.get('use_ocr') == 'on'

            start_time = time.time()

            # 4. 执行 YOLO 检测
            # utils_yolo 返回结构: {'image_url': 'results/xxx.jpg', 'detections': [...]}
            yolo_result = yolo_detector.detect(save_path, conf_thres, iou_thres)
            
            ocr_data = []
            
            # 5. 如果开启 OCR，对检测到的目标进行识别
            if use_ocr and yolo_result['detections']:
                print("开始执行 OCR 识别...")
                # 确保OCR模型已就绪
                if not ocr_detector.is_ready:
                    print("OCR模型正在初始化中，跳过本次OCR...")
                else:
                    for det in yolo_result['detections']:
                        # utils_yolo 已经帮忙把裁剪图保存到了 det['crop_path']
                        crop_path = det['crop_path']
                        
                        # 只有当图片存在时才识别
                        if os.path.exists(crop_path):
                            ocr_res = ocr_detector.recognize(crop_path)
                            if ocr_res:
                                ocr_data.append({
                                    'text': ocr_res['text'],
                                    'conf': ocr_res['conf'],
                                    'type': det['label'] # 关联车辆类型
                                })
            else:
                print("未启用 OCR 识别 或 未检测到目标，跳过 OCR 步骤。")
            

            # 计算总耗时
            time_elapsed = round(time.time() - start_time, 3)
            # 删除图片
            if os.path.exists(save_path):
                os.remove(save_path)
            # 删除裁剪图
            for det in yolo_result['detections']:
                crop_path = det['crop_path']
                if os.path.exists(crop_path):
                    os.remove(crop_path)

            # 6. 构造返回数据
            return jsonify({
                'success': True,
                # 注意：前端需要 static 路径，utils_yolo 返回的是相对路径 "results/xxx"
                'image_url': url_for('static', filename=yolo_result['image_url'].replace('\\', '/')),
                'time_elapsed': time_elapsed,
                'results': yolo_result['detections'], # YOLO 框信息
                'ocr_data': ocr_data                  # OCR 文本信息
            })

        except Exception as e:
            print(f"识别出错: {e}")
            return jsonify({'success': False, 'message': str(e)})

    return render_template('recognition.html')

# ... (其余路由代码: records, monitor, camera, config, password, login, logout, init_data 保持不变) ...

@app.route('/records')
def records():
    return render_template('records.html')

@app.route('/monitor')
def monitor():
    cameras = Camera.query.all()
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
        flash('摄像头添加成功', 'success')
    else:
        flash('请填写完整信息', 'warning')
    return redirect(url_for('system_config'))

@app.route('/camera/delete/<int:cam_id>')
def delete_camera(cam_id):
    cam = Camera.query.get(cam_id)
    if cam:
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
            db.session.commit()
            flash('全局参数配置已更新', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')
        return redirect(url_for('system_config'))
    return render_template('config.html', config=config_item, cameras=cameras)

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
        db.create_all() 
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            new_admin = User(username='admin')
            new_admin.set_password('admin')
            db.session.add(new_admin)
            db.session.commit()
            print("管理员账号自动创建成功")

if __name__ == '__main__':
    init_data()
    app.run(debug=True, host='0.0.0.0')