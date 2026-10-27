#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py — 경로·상수·설정 로드 (JARVIS 백엔드 서버)"""

import json
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# 경로 / 설정
# ---------------------------------------------------------------------------
from app_paths import IS_FROZEN, APP_HOME, WEB_ROOT

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = APP_HOME                              # 쓰기 가능한 루트 (.env, data, logs)
DATA_DIR = os.path.join(BASE_DIR, "data")
WEB_DIR = os.path.join(WEB_ROOT, "web")          # 읽기 전용 정적 UI (패키지 빌드에서는 번들 내부)
LOG_DIR = os.path.join(BASE_DIR, "logs")
ATTACH_DIR = os.path.join(DATA_DIR, "attachments")
PRODUCT_ATTACH_DIR = os.path.join(ATTACH_DIR, "products")
# 패키지 빌드에서는 config.json 을 exe 옆에 둔다 (고객이 수정/보존 가능, 업그레이드 시 유지).
CONFIG_PATH = os.path.join(BASE_DIR if IS_FROZEN else SERVER_DIR, "config.json")
DEPTS_PATH = os.path.join(DATA_DIR, "departments.json")
RECORDS_PATH = os.path.join(DATA_DIR, "records.jsonl")
ACCOUNTS_PATH = os.path.join(DATA_DIR, "accounts.json")
SCHEDULE_PATH = os.path.join(DATA_DIR, "schedule.json")
PRODUCTS_PATH = os.path.join(DATA_DIR, "products.json")
VECTOR_DB_PATH = os.path.join(DATA_DIR, "vector_store.sqlite")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")


def _load_app_version():
    """Read the release version from the VERSION file (single source of truth)."""
    try:
        with open(os.path.join(WEB_ROOT, "VERSION"), "r", encoding="utf-8") as fh:
            value = fh.read().strip()
        if value:
            return value
    except Exception:
        pass
    return "0.0.0-dev"


APP_VERSION = _load_app_version()

DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 8080},
    "jira": {
        "enabled": False,
        "base_url": "",
        "email": "",
        "api_token": "",
        "default_project_key": "",
        "default_issue_type": "",
        "default_subtask_type": "Subtask",
        "project_map": {}
    },
    "ai": {
        "enabled": False,
        "provider": "gemini",  # gemini | openai | deepseek | claude | groq | ollama | openrouter
        "api_key": "",
        "model": "gemini-3.5-flash-lite",
        "base_url": "",
        "allow_user_keys": False,  # Cho phép người dùng sử dụng API key / model cá nhân
        "fallback": {
            "enabled": False,
            "provider": "openai",
            "api_key": "",
            "model": "gpt-4o-mini",
            "base_url": ""
        }
    },
    "anthropic": {
        "enabled": False,
        "api_key": "",
        "model": "claude-sonnet-4-5"
    },
    "voyage": {
        "enabled": False,
        "provider": "voyage",
        "api_key": "",
        "model": "voyage-3-lite",
        "base_url": ""
    },
    "workspace": {
        "name": "ARGOS WORKS",
        "title": "업무 인수인계 및 AI 협업 기록 시스템",
        "welcome_greeting": "ARGOS WORKS에 오신 것을 환영합니다",
        "welcome_subtitle": "프로젝트 인수인계, 사내 업무 기록 및 실시간 AI 협업 시스템입니다.",
        "logo_url": "",
        "footer_text": "ARGOS WORKS System © 2026"
    },
    "backup": {
        "dir": "",
        "interval_hours": 24,
        "retention_days": 14,
        "retention_count": 30
    },
    "allow_public_register": False,
    "max_upload_mb": 25
}

DEFAULT_DEPARTMENTS = [
    {
        "id": "dev",
        "name": "연구개발팀 (R&D)",
        "colorIndex": 1,
        "localPrefix": "DEV",
        "customCategories": "기획·전략, 아키텍처 설계, 백엔드 개발, 프론트엔드 개발, UI/UX 디자인, 코드 리뷰, QA·검증, 버그 수정"
    },
    {
        "id": "sales",
        "name": "영업마케팅팀 (Sales)",
        "colorIndex": 2,
        "localPrefix": "SALES",
        "customCategories": "기획·전략, 시장 조사, 고객 미팅, 제안서 작성, 견적·계약, 마케팅 홍보, 고객 지원"
    },
    {
        "id": "mgmt",
        "name": "경영기획팀 (Management)",
        "colorIndex": 3,
        "localPrefix": "MGMT",
        "customCategories": "경영 전략, 사업 기획, 예산·재무, KPI 실적 관리, 투자 유치, 대외 제휴"
    },
    {
        "id": "hr",
        "name": "인사총무팀 (HR)",
        "colorIndex": 4,
        "localPrefix": "HR",
        "customCategories": "채용·면접, 인사 평가, 총무·자산 관리, 복리후생, 사내 행사, 교육 훈련"
    },
    {
        "id": "hq",
        "name": "본사 (HQ)",
        "colorIndex": 5,
        "localPrefix": "HQ",
        "customCategories": "기획·전략, 전사 운영, 총괄 보고, 대외 협력"
    }
]

CATEGORY_KEYWORDS = [
    ("기획·전략", ["기획", "전략", "제안", "기획서"]),
    ("개발·기술", ["개발", "기술", "연구", "설계", "구현"]),
    ("운영·지원", ["운영", "지원", "인프라", "보안"]),
    ("품질·검수", ["검수", "품질", "테스트", "QA"]),
    ("회의·보고", ["회의", "보고", "발표", "미팅"]),
]
VALID_CATEGORIES = [c for c, _ in CATEGORY_KEYWORDS] + ["기타업무"]

SCHEDULE_TYPES = ["연차", "반차", "병가", "출장", "재택", "회의", "기타"]
SCHEDULE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PRODUCT_LIFECYCLES = ["판매 중", "단종 예정", "단종"]
PRODUCT_MODEL_RE = re.compile(r"^[0-9A-Za-z()._\- ]{1,100}$")
PRODUCT_IDNO_RE = re.compile(r"^\d{8}$")

PRODUCT_CATEGORIES = ["일반", "소프트웨어", "하드웨어", "기타"]
SPEC_TEMPLATES = {
    "일반": [],
    "소프트웨어": [
        {"group": "사양", "key": "version", "label": "버전", "maxlen": 40},
        {"group": "사양", "key": "license", "label": "라이선스", "maxlen": 40},
    ],
    "하드웨어": [
        {"group": "사양", "key": "modelNo", "label": "모델 번호", "maxlen": 40},
        {"group": "사양", "key": "power", "label": "정격 전원", "maxlen": 40},
    ],
    "기타": []
}

# Jira 자동 동기화 주기 (초)
JIRA_AUTO_SYNC_INTERVAL_SEC = 180


# ---------------------------------------------------------------------------
# .env 로딩
# ---------------------------------------------------------------------------
def _load_env():
    """Load .env file if present, set as environment variables"""
    env_path = os.path.join(BASE_DIR, '.env')
    if os.path.isfile(env_path):
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    os.environ.setdefault(key.strip(), value.strip())


def log_line(*parts):
    print("[" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "]", *parts, file=sys.stderr, flush=True)


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            for section in cfg:
                if section in user_cfg and isinstance(user_cfg[section], dict):
                    cfg[section].update(user_cfg[section])
                elif section in user_cfg:
                    cfg[section] = user_cfg[section]
        except Exception as e:
            log_line("config.json을 읽는 중 오류 — 기본값 사용:", e)
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log_line("config.json이 없어 기본값으로 새로 만들었습니다:", CONFIG_PATH)

    _load_env()
    from utils.crypto import decrypt_secret

    # --- Jira -----------------------------------------------------------------
    jira_cfg = cfg.setdefault('jira', {
        'enabled': False,
        'base_url': '',
        'email': '',
        'api_token': '',
        'default_project_key': '',
        'default_issue_type': '',
        'default_subtask_type': 'Subtask',
        'project_map': {}
    })

    # JIRA_ENABLED: .env에 URL/이메일/토큰만 넣고 이 값을 처리하지 않으면
    # jira.enabled가 계속 False로 남아 모든 Jira 호출이 조용히 no-op 되었다.
    if os.environ.get('JIRA_ENABLED'):
        jira_cfg['enabled'] = os.environ['JIRA_ENABLED'].strip().lower() in ('1', 'true', 'yes', 'on')

    # Override sensitive config from environment (with transparent AES-256 decryption)
    if os.environ.get('JIRA_API_TOKEN'):
        jira_cfg['api_token'] = decrypt_secret(os.environ['JIRA_API_TOKEN'])
    elif jira_cfg.get('api_token'):
        jira_cfg['api_token'] = decrypt_secret(jira_cfg['api_token'])

    if os.environ.get('JIRA_EMAIL'):
        jira_cfg['email'] = os.environ['JIRA_EMAIL'].strip()
    if os.environ.get('JIRA_BASE_URL'):
        jira_cfg['base_url'] = os.environ['JIRA_BASE_URL'].strip()
    if os.environ.get('JIRA_PROJECT_KEY'):
        jira_cfg['default_project_key'] = os.environ['JIRA_PROJECT_KEY'].strip()

    # JIRA_PROJECT_MAP: JSON object, e.g. {"dev": {"project_key": "SCRUM", "issue_type": "Task"}}
    raw_project_map = (os.environ.get('JIRA_PROJECT_MAP') or '').strip()
    if raw_project_map:
        parsed_map = None
        try:
            parsed_map = json.loads(raw_project_map)
        except Exception as e:
            log_line("JIRA_PROJECT_MAP 값이 올바른 JSON이 아니어서 무시했습니다:", e)
        if isinstance(parsed_map, dict):
            jira_cfg['project_map'] = parsed_map
        elif parsed_map is not None:
            log_line("JIRA_PROJECT_MAP 값이 JSON 객체가 아니어서 무시했습니다.")

    # AI Configuration (Universal AI)
    ai_cfg = cfg.setdefault('ai', {
        'enabled': False,
        'provider': 'gemini',
        'api_key': '',
        'model': '',
        'base_url': ''
    })
    if os.environ.get('AI_ENABLED'):
        ai_cfg['enabled'] = os.environ['AI_ENABLED'].strip().lower() in ('1', 'true', 'yes', 'on')
    if os.environ.get('AI_PROVIDER'):
        ai_cfg['provider'] = os.environ['AI_PROVIDER'].strip().lower()
    if os.environ.get('AI_API_KEY'):
        ai_cfg['api_key'] = decrypt_secret(os.environ['AI_API_KEY'].strip())
    elif ai_cfg.get('api_key'):
        ai_cfg['api_key'] = decrypt_secret(ai_cfg['api_key'])
    if os.environ.get('AI_MODEL'):
        ai_cfg['model'] = os.environ['AI_MODEL'].strip()
    if os.environ.get('AI_BASE_URL'):
        ai_cfg['base_url'] = os.environ['AI_BASE_URL'].strip()
    if os.environ.get('AI_ALLOW_USER_KEYS'):
        ai_cfg['allow_user_keys'] = os.environ['AI_ALLOW_USER_KEYS'].strip().lower() in ('1', 'true', 'yes', 'on')

    # AI Fallback Configuration (Secondary Provider for Failover)
    fb_cfg = ai_cfg.setdefault('fallback', {
        'enabled': False,
        'provider': 'openai',
        'api_key': '',
        'model': 'gpt-4o-mini',
        'base_url': ''
    })
    if os.environ.get('AI_FALLBACK_ENABLED'):
        fb_cfg['enabled'] = os.environ['AI_FALLBACK_ENABLED'].strip().lower() in ('1', 'true', 'yes', 'on')
    if os.environ.get('AI_FALLBACK_PROVIDER'):
        fb_cfg['provider'] = os.environ['AI_FALLBACK_PROVIDER'].strip().lower()
    if os.environ.get('AI_FALLBACK_API_KEY'):
        fb_cfg['api_key'] = decrypt_secret(os.environ['AI_FALLBACK_API_KEY'].strip())
    elif fb_cfg.get('api_key'):
        fb_cfg['api_key'] = decrypt_secret(fb_cfg['api_key'])
    if os.environ.get('AI_FALLBACK_MODEL'):
        fb_cfg['model'] = os.environ['AI_FALLBACK_MODEL'].strip()
    if os.environ.get('AI_FALLBACK_BASE_URL'):
        fb_cfg['base_url'] = os.environ['AI_FALLBACK_BASE_URL'].strip()

    # Legacy Anthropic support
    if os.environ.get('ANTHROPIC_API_KEY'):
        cfg['anthropic']['api_key'] = decrypt_secret(os.environ['ANTHROPIC_API_KEY'])
        if not ai_cfg.get('api_key'):
            ai_cfg['api_key'] = cfg['anthropic']['api_key']
            ai_cfg['provider'] = 'claude'
            ai_cfg['enabled'] = True
    elif cfg.get('anthropic', {}).get('api_key'):
        cfg['anthropic']['api_key'] = decrypt_secret(cfg['anthropic']['api_key'])

    # Keep cfg['anthropic'] in sync if ai is claude
    if ai_cfg.get('provider') in ('claude', 'anthropic'):
        cfg.setdefault('anthropic', {})
        cfg['anthropic']['enabled'] = ai_cfg.get('enabled', False)
        cfg['anthropic']['api_key'] = ai_cfg.get('api_key', '')
        if ai_cfg.get('model'):
            cfg['anthropic']['model'] = ai_cfg['model']

    # Voyage / Embedding Vector DB Configuration
    voyage_cfg = cfg.setdefault('voyage', {
        'enabled': False,
        'provider': 'voyage',
        'api_key': '',
        'model': 'voyage-3-lite',
        'base_url': ''
    })
    if os.environ.get('VOYAGE_ENABLED'):
        voyage_cfg['enabled'] = os.environ['VOYAGE_ENABLED'].strip().lower() in ('1', 'true', 'yes', 'on')
    if os.environ.get('VOYAGE_PROVIDER'):
        voyage_cfg['provider'] = os.environ['VOYAGE_PROVIDER'].strip().lower()
    if os.environ.get('VOYAGE_API_KEY'):
        voyage_cfg['api_key'] = decrypt_secret(os.environ['VOYAGE_API_KEY'].strip())
        if os.environ.get('VOYAGE_ENABLED') is None:
            voyage_cfg['enabled'] = True
    elif voyage_cfg.get('api_key'):
        voyage_cfg['api_key'] = decrypt_secret(voyage_cfg['api_key'])

    if os.environ.get('VOYAGE_API_KEYS'):
        raw_keys = os.environ['VOYAGE_API_KEYS'].strip()
        # Handle comma-separated keys decrypting each if encrypted
        decrypted_keys = [decrypt_secret(k.strip()) for k in raw_keys.split(',') if k.strip()]
        voyage_cfg['api_keys'] = ', '.join(decrypted_keys)
        if not voyage_cfg.get('api_key'):
            voyage_cfg['api_key'] = decrypted_keys[0] if decrypted_keys else ''
        if os.environ.get('VOYAGE_ENABLED') is None:
            voyage_cfg['enabled'] = True
    if os.environ.get('VOYAGE_MODEL'):
        voyage_cfg['model'] = os.environ['VOYAGE_MODEL'].strip()
    if os.environ.get('VOYAGE_BASE_URL'):
        voyage_cfg['base_url'] = os.environ['VOYAGE_BASE_URL'].strip()

    # Workspace Branding Configuration
    ws_cfg = cfg.setdefault('workspace', {
        'name': 'JARVIS',
        'title': '업무 인수인계 및 AI 협업 기록 시스템',
        'welcome_greeting': 'JARVIS에 오신 것을 환영합니다',
        'welcome_subtitle': '연구 및 프로젝트 인수인계, 사내 업무 기록 및 실시간 AI 협업 시스템입니다.',
        'logo_url': '',
        'footer_text': 'JARVIS System © 2026'
    })
    if os.environ.get('WORKSPACE_NAME'):
        ws_cfg['name'] = os.environ['WORKSPACE_NAME'].strip()
    if os.environ.get('WORKSPACE_TITLE'):
        ws_cfg['title'] = os.environ['WORKSPACE_TITLE'].strip()
    if os.environ.get('WORKSPACE_WELCOME_GREETING'):
        ws_cfg['welcome_greeting'] = os.environ['WORKSPACE_WELCOME_GREETING'].strip()
    if os.environ.get('WORKSPACE_WELCOME_SUBTITLE'):
        ws_cfg['welcome_subtitle'] = os.environ['WORKSPACE_WELCOME_SUBTITLE'].strip()
    if os.environ.get('WORKSPACE_LOGO_URL'):
        ws_cfg['logo_url'] = os.environ['WORKSPACE_LOGO_URL'].strip()
    if os.environ.get('WORKSPACE_FOOTER_TEXT'):
        ws_cfg['footer_text'] = os.environ['WORKSPACE_FOOTER_TEXT'].strip()

    # Backup Configuration
    backup_cfg = cfg.setdefault('backup', {
        'dir': '',
        'interval_hours': 24,
        'retention_days': 14,
        'retention_count': 30
    })
    if os.environ.get('BACKUP_DIR'):
        backup_cfg['dir'] = os.environ['BACKUP_DIR'].strip()

    if os.environ.get('ALLOW_PUBLIC_REGISTER'):
        cfg['allow_public_register'] = os.environ['ALLOW_PUBLIC_REGISTER'].strip().lower() in ('1', 'true', 'yes', 'on')

    return cfg


def ensure_dirs():
    for d in (DATA_DIR, WEB_DIR, LOG_DIR, ATTACH_DIR, TEMPLATES_DIR):
        os.makedirs(d, exist_ok=True)



def ensure_seed_files():
    """기존 JSON 시드 파일 생성 — SQLite 전환 후에는 init_db()가 테이블을 자동 생성하므로
    이 함수는 하위 호환성을 위해 유지만 한다. 실제 시드 데이터는 data_store.read_departments()에서
    DB가 비어있을 때 DEFAULT_DEPARTMENTS를 INSERT한다."""
    pass
