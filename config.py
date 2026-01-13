import os
SECRET_KEY = 'DKyWJtfZmKcRvfnJSedkUkJYPfduC5dusTHxyTxt'
basedir = os.path.abspath(os.path.dirname(__file__))
SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'accessflow.db')
SQLALCHEMY_TRACK_MODIFICATIONS = False
SCHEDULER_API_ENABLED = True



