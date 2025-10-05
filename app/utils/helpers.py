import uuid
from datetime import datetime

def generate_id():
    return str(uuid.uuid4())[:8]

def current_date():
    return datetime.now().strftime("%Y-%m-%d")
