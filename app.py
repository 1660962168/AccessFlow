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

app = Flask(__name__)
# 绑定配置文件
app.config.from_object(config)
db.init_app(app)
migrate = Migrate(app, db)
# 定时任务
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/recognition', methods=['GET', 'POST'])
def recognition():
    return render_template('recognition.html')

@app.route('/records')
def records():
    return render_template('records.html')

@app.route('/monitor')
def monitor():
    # 查询所有摄像头数据
    cameras = Camera.query.all()
    return render_template('monitor.html', cameras=cameras)

# --- 新增：专门处理摄像头添加/删除的路由 ---
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

    # 获取所有摄像头列表传给前端
    cameras = Camera.query.order_by(Camera.created_at.desc()).all()

    if request.method == 'POST':
        try:
            # 这里只处理 SystemConfig 的全局参数更新
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

        # 1. 检查输入是否为空
        if not username or not password:
            flash('请输入账号和密码', 'warning')
            return render_template('login.html')

        user = User.query.filter_by(username=username).first()

        # 2. 验证账号是否存在
        if not user:
            flash('账号不存在，请检查用户名', 'danger')
        
        # 3. 验证密码是否正确
        elif not user.check_password(password):
            flash('密码错误，请重新输入', 'danger')
            
        else:
            # 4. 登录成功
            session['username'] = username
            flash('登录成功，欢迎回来', 'success')
            return redirect(url_for('index'))

    return render_template('login.html')

# 退出登录
@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('退出登录成功','success')
    return redirect(url_for('login'))

def init_data():
    with app.app_context():
        # 1. 自动创建所有表 (如果表不存在)
        db.create_all() 
        print("数据库表结构检查/创建完成。")

        # 2. 检查并创建管理员
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            new_admin = User(username='admin')
            new_admin.set_password('admin')
            db.session.add(new_admin)
            db.session.commit()
            print("管理员账号自动创建成功：账号 admin，密码 admin")
        else:
            print("管理员账号已存在。")

if __name__ == '__main__':
    init_data()
    app.run(debug=True, host='0.0.0.0')
