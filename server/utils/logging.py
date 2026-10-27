import sys
import os
import csv
import re
from datetime import datetime, date

from app_paths import APP_HOME

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = APP_HOME
LOG_DIR = os.path.join(BASE_DIR, "logs")

SENSITIVE_PARAM_PATTERN = re.compile(
    r'(?i)(token|key|api_key|password|secret|auth|access_token|csrf)=([^&\s]+)'
)

def mask_query_string(message: str) -> str:
    """Mask sensitive parameters (token, key, password, secret, etc.) in log messages."""
    if not message or not isinstance(message, str):
        return message
    return SENSITIVE_PARAM_PATTERN.sub(r'\1=***', message)

def log_line(*parts):
    masked_parts = [mask_query_string(str(p)) if isinstance(p, str) else p for p in parts]
    print("[" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "]", *masked_parts, file=sys.stderr)

def access_log(request_ip, action, status, extra=""):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fname = os.path.join(LOG_DIR, "access_" + date.today().strftime("%Y%m%d") + ".csv")
        is_new = not os.path.exists(fname)
        safe_extra = mask_query_string(str(extra))
        with open(fname, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["시각", "IP", "동작", "상태", "비고"])
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), request_ip, action, status, safe_extra])
    except Exception as e:
        log_line("access_log 기록 실패:", e)
