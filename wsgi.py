import sys
import os

project_home = u'/home/shadrack/python/kazi-backend'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

os.environ['FLASK_APP'] = 'app.py'

from app import app as application  
