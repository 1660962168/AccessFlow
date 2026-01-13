from flask import Flask, session, render_template, jsonify, request, redirect, url_for, flash, send_file
import config
from exts import db
from models import *
from flask_migrate import Migrate
from flask_apscheduler import APScheduler

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
@app.route('/records')
def records():
    return render_template('records.html')

@app.route('/password', methods=['GET','POST'])
def password():
    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        user = User.query.filter_by(username=session.get('username')).first()
        if user and user.check_password(old_password):
            user.password = new_password
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
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['username'] = username
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'danger')
    return render_template('login.html')

# 退出登录
@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('退出登录成功','success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0')
