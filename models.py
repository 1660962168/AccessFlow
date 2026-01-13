from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from exts import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# 新增：停车记录模型
class ParkingRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(20), nullable=False)  # 车牌号
    entry_time = db.Column(db.DateTime, default=datetime.now) # 入场时间
    exit_time = db.Column(db.DateTime, nullable=True)         # 出场时间
    status = db.Column(db.String(10), default='入场')         # 状态：入场/出场
    fee = db.Column(db.Float, default=0.0)                    # 费用
    
    def __repr__(self):
        return f'<ParkingRecord {self.plate_number}>'
    
class SystemConfig(db.Model):
    __tablename__ = 'system_config'
    id = db.Column(db.Integer, primary_key=True)
    
    # 算法默认参数
    conf_thres = db.Column(db.Float, default=0.5)      # 置信度
    iou_thres = db.Column(db.Float, default=0.45)      # IOU阈值
    use_ocr = db.Column(db.Boolean, default=True)      # 是否开启OCR
    
    # 输入源
    camera_source = db.Column(db.String(255), default='0') # 默认为本地相机
    
    # 数据维护
    retention_days = db.Column(db.Integer, default=30) # 记录保留天数
    
    # 更新时间
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return '<SystemConfig %r>' % self.id