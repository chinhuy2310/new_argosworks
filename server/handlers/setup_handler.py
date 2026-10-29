# -*- coding: utf-8 -*-
"""setup_handler.py — Initial Enterprise B2B Setup & Onboarding Wizard.
Enforces Master Admin bootstrap, offline/signed license verification, and default
department/company initialization before open operation.
"""

import os
import json
from datetime import datetime
from db import query, get_one, execute, transaction
from utils.logging import access_log


_setup_completed_cache = None

def reset_setup_cache():
    global _setup_completed_cache
    _setup_completed_cache = None

def check_needs_setup():
    """시스템에 등록된 사용자가 0명인지 확인하여 초기 설정 마법사 실행 여부를 반환한다."""
    try:
        global _setup_completed_cache
        if _setup_completed_cache is True:
            return False
        cnt = get_one("SELECT COUNT(*) AS c FROM users")
        if cnt and cnt["c"] > 0:
            _setup_completed_cache = True
        return (cnt["c"] == 0) if cnt else True
    except Exception:
        return False


def handle_get_setup_status(handler, parsed, ip):
    """GET /api/setup/status — 초기 설정 필요 여부 및 기본 부서 프리셋 조회."""
    needs_setup = check_needs_setup()
    default_departments = [
        {"id": "dev", "name": "연구개발팀 (R&D)", "prefix": "DEV", "color_index": 1},
        {"id": "sales", "name": "영업마케팅팀 (Sales)", "prefix": "SALES", "color_index": 2},
        {"id": "hr", "name": "인사총무팀 (HR)", "prefix": "HR", "color_index": 3},
        {"id": "mgmt", "name": "경영기획팀 (Management)", "prefix": "MGMT", "color_index": 4}
    ]

    handler._send_json(200, {
        "ok": True,
        "needs_setup": needs_setup,
        "default_departments": default_departments
    })


def handle_post_setup_verify_license(handler, raw_body, ip):
    """POST /api/setup/verify-license — 마법사 1단계: 라이선스 키 사전 검증."""
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}

    license_key = (body.get("license_key") or "").strip()
    if not license_key:
        handler._send_json(400, {"ok": False, "error": "라이선스 키를 입력해주세요."})
        return

    from services.license_manager import verify_license_key
    ok, msg, data = verify_license_key(license_key)
    if not ok:
        handler._send_json(400, {"ok": False, "error": msg})
        return

    handler._send_json(200, {
        "ok": True,
        "message": msg,
        "license": data
    })


def handle_post_setup_complete(handler, raw_body, ip):
    """POST /api/setup/complete — 엔터프라이즈 초기 설정 마법사 일괄 커밋.
    1단계: 라이선스 활성화
    2단계: Master Admin 계정 생성 (status='active', role='admin', disabled=0)
    3단계: 회사명 및 기본 부서 등록
    """
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}

    # Bootstrap Token Enforcement: If ARGOS_BOOTSTRAP_TOKEN is configured in environment, verify it
    required_bootstrap = os.environ.get("ARGOS_BOOTSTRAP_TOKEN", "").strip()
    if required_bootstrap:
        provided_bootstrap = (body.get("bootstrap_token") or handler.headers.get("X-Bootstrap-Token") or "").strip()
        import hmac
        if not hmac.compare_digest(provided_bootstrap, required_bootstrap):
            handler._send_json(403, {
                "ok": False,
                "error": "시스템 초기 설정을 완료하려면 유효한 부트스트랩 토큰(Bootstrap Token)이 필요합니다."
            })
            return

    if not check_needs_setup():
        handler._send_json(403, {"ok": False, "error": "시스템 초기 설정이 이미 완료되었습니다."})
        return

    license_key = (body.get("license_key") or "").strip()
    admin_info = body.get("admin") or {}
    company_name = (body.get("company_name") or "Argos Enterprise").strip()
    departments = body.get("departments") or []
    admin_dept_id = (body.get("admin_dept_id") or "").strip()

    # 1. 라이선스 검증
    from services.license_manager import verify_license_key, activate_license
    lic_ok, lic_msg, lic_data = verify_license_key(license_key)
    if not lic_ok:
        handler._send_json(400, {"ok": False, "error": f"라이선스 검증 실패: {lic_msg}"})
        return

    # 2. Master Admin 입력 검증
    username = (admin_info.get("username") or "").strip()
    name = (admin_info.get("name") or "").strip()
    password = admin_info.get("password") or ""
    email = (admin_info.get("email") or "").strip()

    if not username or not name or not password:
        handler._send_json(400, {"ok": False, "error": "마스터 관리자 ID, 이름, 비밀번호는 필수 항목입니다."})
        return

    if len(username) < 3:
        handler._send_json(400, {"ok": False, "error": "관리자 ID는 최소 3자 이상이어야 합니다."})
        return

    from services.auth import validate_username_format
    try:
        username = validate_username_format(username)
    except ValueError as ve:
        handler._send_json(400, {"ok": False, "error": str(ve)})
        return

    if len(password) < 8:
        handler._send_json(400, {"ok": False, "error": "관리자 비밀번호는 보안을 위해 최소 8자 이상이어야 합니다."})
        return

    # 3. 부서 목록 기본값 보정
    if not departments:
        departments = [
            {"id": "dev", "name": "연구개발팀 (R&D)", "prefix": "DEV", "color_index": 1},
            {"id": "sales", "name": "영업마케팅팀 (Sales)", "prefix": "SALES", "color_index": 2},
            {"id": "hr", "name": "인사총무팀 (HR)", "prefix": "HR", "color_index": 3},
            {"id": "mgmt", "name": "경영기획팀 (Management)", "prefix": "MGMT", "color_index": 4}
        ]

    # 관리자 소속 부서 결정
    # dept_ids 가 비어 있으면(부서 항목에 id 누락) admin_dept_id 결정 단계에서
    # IndexError(500)가 발생하므로 명시적으로 검증한다.
    dept_ids = [str(d.get("id")).strip().lower() for d in departments if d.get("id")]
    dept_ids = [d for d in dept_ids if d]
    if not dept_ids:
        handler._send_json(400, {
            "ok": False,
            "error": "최소 1개 이상의 유효한 부서(id 포함)를 등록해야 초기 설정을 완료할 수 있습니다."
        })
        return
    admin_dept_id = str(admin_dept_id or "").strip().lower()
    if not admin_dept_id or admin_dept_id not in dept_ids:
        admin_dept_id = "mgmt" if "mgmt" in dept_ids else dept_ids[0]

    # 4. 원자적(Atomic) 검사 및 트랜잭션 일괄 저장 (Race condition 방지)
    from services.auth import hash_password, create_session, _effective_pbkdf2_rounds
    salt, pwd_hash = hash_password(password)
    pwd_iterations = _effective_pbkdf2_rounds()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _do_setup(conn):
        cur = conn.cursor()

        # Atomic Race check: Ensure no user was registered concurrently
        cur.execute("SELECT COUNT(*) AS c FROM users")
        row = cur.fetchone()
        user_count = row[0] if isinstance(row, (tuple, list)) else row.get("c", 0)
        if user_count > 0:
            raise RuntimeError("시스템 초기 설정이 이미 완료되었습니다 (다른 관리자가 등록을 마쳤습니다).")

        # (1) 부서 및 카드 시퀀스 등록
        for d in departments:
            d_id = (d.get("id") or "").strip().lower()
            d_name = (d.get("name") or d_id).strip()
            d_color = int(d.get("color_index") or 1)
            d_prefix = (d.get("prefix") or d_id.upper()).strip()
            if not d_id:
                continue

            cur.execute("""
                INSERT OR REPLACE INTO departments (id, name, color_index, local_prefix, jira_key, custom_categories)
                VALUES (?, ?, ?, ?, '', '')
            """, (d_id, d_name, d_color, d_prefix))

            cur.execute("""
                INSERT OR IGNORE INTO card_sequences (dept_id, last_seq)
                VALUES (?, 0)
            """, (d_id,))

        # (2) Master Admin 계정 생성 (status='active', role='admin', is_admin=1, disabled=0)
        cur.execute("""
            INSERT INTO users (username, name, dept_id, email, salt, password_hash, is_admin, role, disabled, status, created_at, hash_algo, iterations)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'admin', 0, 'active', ?, 'pbkdf2_sha256', ?)
        """, (username, name, admin_dept_id, email, salt, pwd_hash, now_str, pwd_iterations))

    try:
        transaction(_do_setup)
    except RuntimeError as re:
        handler._send_json(403, {"ok": False, "error": str(re)})
        return
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": f"초기 설정 저장 실패: {str(e)}"})
        return

    admin_user = get_one("SELECT id, name, dept_id, email, role FROM users WHERE username = ? LIMIT 1", (username,))

    # 5. 라이선스 정보 활성화 반영
    act_ok, act_msg = activate_license(license_key)
    if not act_ok:
        # 라이선스 활성화 실패 시에도 기본 활성화 기록
        execute("""
            UPDATE license_info
            SET customer_name = ?, license_key = ?, is_active = 1, updated_at = ?
            WHERE id = 1
        """, (company_name, license_key, now_str))

    # 6. 회사명 업데이트 (license_info customer_name 반영)
    execute("""
        UPDATE license_info SET customer_name = ? WHERE id = 1
    """, (company_name,))

    # 7. Audit Log 기록
    from services.audit_logger import log_audit
    admin_session = {"name": name, "org": admin_dept_id, "email": email, "role": "admin", "isAdmin": True}
    log_audit(
        session=admin_session,
        ip=ip,
        action="SYSTEM_SETUP_COMPLETED",
        target_type="system",
        target_id=company_name,
        details={
            "admin_username": username,
            "admin_name": name,
            "admin_dept": admin_dept_id,
            "departments_count": len(departments),
            "customer_name": company_name,
            "license_customer": lic_data.get("customer")
        }
    )

    access_log(ip, "system_setup_complete", 200, f"{name}|{username}|{company_name}")

    # 8. 자동 세션 발급 및 로그인 처리
    token = create_session(name, admin_dept_id, email, user_id=admin_user["id"] if admin_user else None)
    cookie_hdr = handler._make_auth_cookie_header(token)

    handler._send_json(200, {
        "ok": True,
        "token": token,
        "message": f"'{company_name}' 시스템 초기 설정이 성공적으로 완료되었습니다.",
        "user": {
            "name": name,
            "username": username,
            "org": admin_dept_id,
            "department": admin_dept_id,
            "email": email,
            "isAdmin": True,
            "role": "admin"
        }
    }, extra_headers=[cookie_hdr])
