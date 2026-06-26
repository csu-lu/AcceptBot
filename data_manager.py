import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
STATE_FILE = os.path.join(os.path.dirname(__file__), 'state.json')

DEFAULT_CONFIG = {
    "url_1": "",
    "username_1": "",
    "password_1": "",
    "url_2": "",
    "username_2": "",
    "password_2": "",
    "send_key": "",
    "poll_interval_hours": 4,
    "send_mode": "查询完立即发送",
    "daily_report_hour": 19
}

DEFAULT_STATE = {
    "last_status_1": "暂无",
    "last_status_2": "暂无",
    "last_daily_report_date": "",
    "history": {}
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_STATE.copy()

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=4)
