import os
import time
import json
from datetime import datetime
from services.auth import (
    account_key, read_accounts, write_accounts, hash_password, verify_password,
    create_session, is_admin_user, get_user_by_login, get_user_by_id, create_user, safe_delete_user
)
from services.data_store import _save_lock, read_departments
from db import get_one, transaction
from utils.text import dept_by_id
from utils.logging import access_log, log_line

# ---- /api/account/check (POST) — 이름+소속이 이미 계정이 있는지(비번 물어볼지,
# 새로 만들지) 로그인 폼이 미리 확인할 때 씀 ----
def handle_account_check(handler, raw_body, ip):
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    name = (payload.get("name") or "").strip()
    org = (payload.get("org") or "").strip()
    if not name or not org:
        handler._send_json(400, {"ok": False, "error": "이름과 소속을 입력해주세요."})
        return
    user = get_one("SELECT 1 FROM users WHERE name = ? AND dept_id = ? LIMIT 1", (name, org))
    # Prevent unauthenticated user enumeration: If public registration is disabled,
    # always direct caller to standard password verification stage
    from config import load_config
    cfg = load_config()
    allow_pub = cfg.get("allow_public_register", False)
    if os.environ.get("ALLOW_PUBLIC_REGISTER"):
        allow_pub = os.environ.get("ALLOW_PUBLIC_REGISTER", "").strip().lower() in ("1", "true", "yes", "on")

    if not allow_pub:
        handler._send_json(200, {"ok": True, "exists": True})
        return

    handler._send_json(200, {"ok": True, "exists": bool(user)})

# ---- /api/account/register (POST) — 계정 발급 요청 (관리자 승인 워크플로) ----
def handle_account_register(handler, raw_body, ip):
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return

    # Check ALLOW_PUBLIC_REGISTER policy: unless enabled, public signups are rejected
    from config import load_config
    cfg = load_config()
    allow_pub = cfg.get("allow_public_register", False)
    if os.environ.get("ALLOW_PUBLIC_REGISTER"):
        allow_pub = os.environ.get("ALLOW_PUBLIC_REGISTER", "").strip().lower() in ("1", "true", "yes", "on")

    if not allow_pub:
        # Check if caller has active admin session creating a user on behalf of team
        caller_session = handler._get_session_optional() if hasattr(handler, "_get_session_optional") else getattr(handler, "session", None)
        from services.auth import is_admin_user
        if not caller_session or not is_admin_user(caller_session):
            handler._send_json(403, {
                "ok": False,
                "error": "시스템 보안 정책에 의해 공개 회원가입(Public Register)이 비활성화되어 있습니다. 관리자에게 계정 생성을 요청하세요."
            })
            return

    from services.license_manager import check_seat_available
    avail, seat_err = check_seat_available()
    if not avail:
        handler._send_json(403, {"ok": False, "error": seat_err or "라이선스 허용 사용자 수(Seat) 제한에 도달했습니다."})
        return

    username = (payload.get("username") or "").strip()
    name = (payload.get("name") or "").strip()
    org = (payload.get("org") or payload.get("department") or "").strip()
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""

    if not username:
        handler._send_json(400, {"ok": False, "error": "ArgosWorks ID(아이디)를 입력해주세요."})
        return
    if not name:
        handler._send_json(400, {"ok": False, "error": "이름(성명)을 입력해주세요."})
        return
    if len(password) < 8:
        handler._send_json(400, {"ok": False, "error": "보안 강화를 위해 비밀번호는 최소 8자 이상이어야 합니다."})
        return

    depts = read_departments()
    if not org and depts:
        org = depts[0]["id"]
    elif not dept_by_id(depts, org):
        if depts:
            org = depts[0]["id"]
        else:
            org = "dev"

    with _save_lock:
        salt_hex, hash_hex = hash_password(password)
        try:
            # All regular registrations enter pending state; admin creation is exclusively reserved for Setup Wizard
            new_user = create_user(
                name=name,
                username=username,
                org=org,
                email=email,
                salt=salt_hex,
                hash_pwd=hash_hex,
                role="member",
                is_admin=False,
                status="pending",
                disabled=1
            )
        except ValueError as val_err:
            handler._send_json(409, {"ok": False, "exists": True, "error": str(val_err)})
            return
        except Exception as e:
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str:
                handler._send_json(409, {"ok": False, "exists": True, "error": "이미 사용 중인 ID 또는 이메일입니다."})
                return
            log_line("[Auth] Account registration error:", e)
            handler._send_json(500, {"ok": False, "error": "계정 등록 처리 중 오류가 발생했습니다. 관리자에게 문의하세요."})
            return

    # Trigger Admin notification + Webhook
        access_log(ip, "account_register_request", 200, "%s|%s (Pending Approval)" % (name, org))
        from services.audit_logger import log_audit
        log_audit(
            session={"name": name, "org": org, "email": email, "role": "pending"},
            ip=ip,
            action="USER_REGISTER_REQUEST",
            target_type="user",
            target_id=username,
            details={"name": name, "org": org, "email": email, "status": "pending"}
        )
        try:
            from services.notification_service import add_notification
            add_notification(
                recipient_name="관리자",
                notif_type="signup",
                title="🔔 신규 계정 가입 승인 요청",
                content=f"{name} ({username} / {org}) 님이 계정 발급 승인을 요청했습니다.",
                tag="가입요청",
                tag_type="signup"
            )
        except Exception:
            pass

        handler._send_json(200, {
            "ok": True,
            "pending": True,
            "message": "계정 발급 요청이 접수되었습니다. 관리자(Admin) 승인 완료 후 로그인하실 수 있습니다."
        })

# ---- /api/account/login (POST) — 기존 계정 비밀번호 확인 ----
def handle_account_login(handler, raw_body, ip):
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    login_id = (payload.get("username") or payload.get("name") or payload.get("identifier") or "").strip()
    org = (payload.get("org") or payload.get("department") or "").strip()
    password = payload.get("password") or ""

    from services.auth import check_login_rate_limit, record_login_failure, clear_login_failures
    allowed, rate_msg = check_login_rate_limit(ip, login_id)
    if not allowed:
        handler._send_json(429, {"ok": False, "error": rate_msg})
        return

    acc = get_user_by_login(login_id, org)
    if not acc or not verify_password(password, acc.get("salt", ""), acc.get("password_hash", ""), iterations=acc.get("iterations"), user_id=acc.get("id")):
        record_login_failure(ip, login_id)
        access_log(ip, "account_login", 401, "%s|%s" % (login_id, org))
        from services.audit_logger import log_audit
        log_audit(
            session={"name": login_id, "org": org or "unknown"},
            ip=ip,
            action="LOGIN_FAILED",
            target_type="auth",
            target_id=login_id,
            details={"reason": "Invalid credentials"}
        )
        handler._send_json(401, {"ok": False, "error": "아이디(또는 이메일) 또는 비밀번호가 올바르지 않습니다."})
        return

    acc_status = acc.get("status")
    if acc_status == "pending":
        from services.audit_logger import log_audit
        log_audit(
            session={"name": login_id, "org": org or "unknown"},
            ip=ip,
            action="LOGIN_FAILED",
            target_type="auth",
            target_id=login_id,
            details={"reason": "Account pending approval"}
        )
        handler._send_json(403, {"ok": False, "error": "해당 계정은 관리자 승인 대기(Pending Approval) 상태입니다. 사내 관리자의 승인 완료 후 이용 가능합니다."})
        return
    elif acc_status == "rejected":
        from services.audit_logger import log_audit
        log_audit(
            session={"name": login_id, "org": org or "unknown"},
            ip=ip,
            action="LOGIN_FAILED",
            target_type="auth",
            target_id=login_id,
            details={"reason": "Account request rejected"}
        )
        handler._send_json(403, {"ok": False, "error": "계정 가입 요청이 반려되었습니다. 사내 관리자에게 문의하세요."})
        return
    elif (acc.get("disabled") or acc.get("is_active") is False
          or acc_status not in (None, "", "active")):
        from services.audit_logger import log_audit
        log_audit(
            session={"name": login_id, "org": org or "unknown"},
            ip=ip,
            action="LOGIN_FAILED",
            target_type="auth",
            target_id=login_id,
            details={"reason": "Account disabled"}
        )
        handler._send_json(403, {"ok": False, "error": "비활성화(잠금)된 계정입니다. 관리자에게 문의하세요."})
        return

    clear_login_failures(ip, login_id)
    name = acc.get("name", login_id)
    username = acc.get("username", login_id)
    # Never invent a department: an account without dept_id must not be silently
    # placed into 'dev' (that would grant another department's records).
    org = (acc.get("dept_id") or acc.get("org") or "").strip()
    email = acc.get("email", "")
    avatar_url = acc.get("avatar_url", "") or ""
    token = create_session(name, org, email, user_id=acc.get("id"))
    access_log(ip, "account_login", 200, "%s|%s" % (name, org))
    is_adm = bool(acc.get("role") == "admin" or acc.get("is_admin") == 1 or is_admin_user(acc))
    from services.auth import get_user_role
    user_role = get_user_role(acc)
    from services.audit_logger import log_audit
    log_audit(
        session={"name": name, "org": org, "email": email, "role": user_role},
        ip=ip,
        action="LOGIN",
        target_type="auth",
        target_id=username,
        details={"name": name, "org": org}
    )
    cookie_hdr = handler._make_auth_cookie_header(token)
    from middleware_security import generate_csrf_token
    csrf_token = generate_csrf_token(token)
    csrf_cookie = ("Set-Cookie", f"argos_csrf={csrf_token}; Path=/; SameSite=Lax; Max-Age=86400")
    handler._send_json(200, {
        "ok": True,
        "token": token,
        "csrfToken": csrf_token,
        "user": {
            "name": name,
            "username": username,
            "org": org,
            "department": org,
            "email": email,
            "avatarUrl": avatar_url,
            "isAdmin": is_adm,
            "role": user_role
        }
    }, extra_headers=[cookie_hdr, csrf_cookie])

# ---- /api/account/logout (POST) — 세션 삭제 ----
def handle_account_logout(handler, raw_body, ip):
    session = handler._get_session_optional()
    if session:
        from services.audit_logger import log_audit
        log_audit(session=session, ip=ip, action="LOGOUT", target_type="auth", target_id=session.get("name"))
    token = handler._extract_token() if hasattr(handler, "_extract_token") else None
    if token:
        try:
            from services.auth import delete_session
            delete_session(token)
        except Exception:
            pass
    logout_cookie_hdr = handler._make_logout_cookie_header()
    handler._send_json(200, {"ok": True}, extra_headers=[logout_cookie_hdr])

# NOTE: GET /api/account/logout intentionally has no handler and no route.
# Logout is POST-only so a link or <img> tag cannot terminate the session
# (CSRF logout); the GET branch that used to live here was removed.

# ---- /api/account/logout-all (POST) — 모든 기기에서 세션 강제 만료 ----
def handle_account_logout_all(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    try:
        from services.auth import delete_all_user_sessions
        delete_all_user_sessions(session.get("name"))
    except Exception:
        pass
    logout_cookie_hdr = handler._make_logout_cookie_header()
    handler._send_json(200, {"ok": True, "message": "모든 기기에서 로그아웃되었습니다."}, extra_headers=[logout_cookie_hdr])


# ---- /api/account/update-profile (POST) — 내 정보(이름, 이메일, 소속, 비밀번호) 수정 ----
def handle_account_update_profile(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문입니다."})
        return

    cur_name = session.get("name", "").strip()
    cur_org = session.get("org", "").strip()
    cur_email = session.get("email", "").strip()

    new_name = (payload.get("name") or cur_name).strip()
    # An omitted "email" field must keep the stored value (previously it was wiped).
    if "email" in payload:
        new_email = str(payload.get("email") or "").strip()
    else:
        new_email = cur_email
    requested_org = (payload.get("org") or payload.get("department") or cur_org).strip()
    new_org = requested_org
    cur_password = (payload.get("current_password") or payload.get("old_password") or "").strip()
    new_password = (payload.get("password") or "").strip()
    confirm_password = (payload.get("confirm_password") or "").strip()

    if not new_name:
        handler._send_json(400, {"ok": False, "error": "이름은 필수 항목입니다."})
        return

    from db import execute
    # Prefer the immutable session id: the name/email stored in the session row are
    # denormalised copies, so after an admin rename the old lookup returned 404 and
    # the user could not change their own password until they logged in again.
    user_row = None
    sess_uid = session.get("id")
    if sess_uid is None:
        sess_uid = session.get("user_id")
    if isinstance(sess_uid, str) and sess_uid.strip().isdigit():
        sess_uid = int(sess_uid.strip())
    if sess_uid not in (None, ""):
        user_row = get_one(
            "SELECT id, username, name, dept_id, email, avatar_url, salt, password_hash, iterations, is_admin FROM users WHERE id = ? LIMIT 1",
            (sess_uid,)
        )
    if not user_row:
        user_row = get_one(
            "SELECT id, username, name, dept_id, email, avatar_url, salt, password_hash, iterations, is_admin FROM users WHERE (name = ? AND dept_id = ?) OR (email != '' AND email = ?) LIMIT 1",
            (cur_name, cur_org, cur_email)
        )

    if not user_row:
        handler._send_json(404, {"ok": False, "error": "사용자 계정을 찾을 수 없습니다."})
        return

    user_id = user_row["id"]
    salt = user_row["salt"]
    pwd_hash = user_row["password_hash"]
    pwd_iterations = user_row.get("iterations") or 600000
    cur_avatar = user_row.get("avatar_url") or ""
    new_avatar = cur_avatar

    avatar_data = payload.get("avatar_data")
    avatar_url_param = payload.get("avatar_url")

    if avatar_data:
        try:
            import base64
            import io
            from PIL import Image
            from config import ATTACH_DIR

            if "," in avatar_data:
                avatar_data = avatar_data.split(",", 1)[1]
            img_bytes = base64.b64decode(avatar_data)
            if 0 < len(img_bytes) <= 5 * 1024 * 1024:
                # Validate that the payload really is a raster image and derive the
                # extension from the actual format, so the served file carries a
                # correct MIME type (previously every avatar was stored as .png).
                with Image.open(io.BytesIO(img_bytes)) as probe:
                    fmt = (probe.format or "").upper()
                ext = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}.get(fmt)
                if ext:
                    avatars_dir = os.path.join(ATTACH_DIR, "avatars")
                    os.makedirs(avatars_dir, exist_ok=True)
                    fname = f"user_{user_id}_{int(time.time())}{ext}"
                    dest = os.path.join(avatars_dir, fname)
                    with open(dest, "wb") as f:
                        f.write(img_bytes)
                    new_avatar = f"/api/attachments/avatars/{fname}"
        except Exception:
            pass
    elif avatar_url_param is not None:
        # Only allow clearing the avatar or an app-relative / HTTPS URL. Arbitrary
        # values (e.g. "javascript:...") must never reach an <img src> attribute.
        candidate = str(avatar_url_param).strip()
        if not candidate or candidate.startswith("/") or candidate.lower().startswith("https://"):
            new_avatar = candidate

    if new_password or cur_password or confirm_password:
        if not cur_password:
            handler._send_json(400, {"ok": False, "error": "현재 비밀번호를 입력해주세요."})
            return
        if not new_password:
            handler._send_json(400, {"ok": False, "error": "새 비밀번호를 입력해주세요."})
            return
        # The confirmation fields are mandatory on the API too (the browser form is not
        # the only client): a typo in an unchecked password would lock the account out.
        if not confirm_password:
            handler._send_json(400, {"ok": False, "error": "새 비밀번호 확인을 입력해주세요."})
            return
        if new_password != confirm_password:
            handler._send_json(400, {"ok": False, "error": "새 비밀번호가 일치하지 않습니다."})
            return
        if len(new_password) < 8:
            handler._send_json(400, {"ok": False, "error": "보안 강화를 위해 비밀번호는 최소 8자 이상이어야 합니다."})
            return
        from services.auth import (
            verify_password, _effective_pbkdf2_rounds,
            check_login_rate_limit, record_login_failure, clear_login_failures,
        )
        # The password-change form is a second place where the account password can be
        # guessed from a stolen session, so it shares the login lockout counter.
        login_ident = (user_row.get("username") or cur_name or "").strip().lower()
        allowed, rate_msg = check_login_rate_limit(ip, login_ident)
        if not allowed:
            handler._send_json(429, {"ok": False, "error": rate_msg})
            return
        if not verify_password(cur_password, user_row["salt"], user_row["password_hash"], iterations=user_row.get("iterations"), user_id=user_row.get("id")):
            record_login_failure(ip, login_ident)
            handler._send_json(400, {"ok": False, "error": "현재 비밀번호가 일치하지 않습니다."})
            return
        clear_login_failures(ip, login_ident)
        salt, pwd_hash = hash_password(new_password)
        pwd_iterations = _effective_pbkdf2_rounds()

    if new_org:
        depts = read_departments()
        if not any(d["id"] == new_org for d in depts):
            handler._send_json(400, {"ok": False, "error": "유효하지 않은 부서(소속)입니다."})
            return

    # 소속(부서) 변경은 열람 가능한 업무/일정 범위(RBAC scope)를 바꾸므로
    # 일반 사용자의 self-service 변경은 즉시 반영하지 않고 관리자 승인 요청으로 남긴다.
    dept_change_pending = False
    if new_org and new_org.lower() != (cur_org or "").lower():
        if not is_admin_user(session):
            dept_change_pending = True
            new_org = cur_org

    # Check if duplicate name+dept exists with a different user id
    dup = get_one(
        "SELECT id FROM users WHERE name = ? AND dept_id = ? AND id != ? LIMIT 1",
        (new_name, new_org, user_id)
    )
    if dup:
        handler._send_json(409, {"ok": False, "error": "해당 소속에 이미 동일한 이름의 사용자가 존재합니다."})
        return

    # Number of other devices that were logged out because the password changed.
    revoked = {"sessions": 0}
    try:
        def _update(conn):
            cur = conn.cursor()
            cur.execute(
                """UPDATE users
                   SET name = ?, email = ?, dept_id = ?, avatar_url = ?, salt = ?, password_hash = ?,
                       iterations = ?, hash_algo = 'pbkdf2_sha256'
                   WHERE id = ?""",
                (new_name, new_email, new_org, new_avatar, salt, pwd_hash, pwd_iterations, user_id)
            )
            # Update current session table via extracted cookie or bearer token
            token = handler._extract_token() if hasattr(handler, "_extract_token") else None
            token_hash = None
            if token:
                from services.auth import hash_session_token
                token_hash = hash_session_token(token)
                cur.execute(
                    """UPDATE sessions
                       SET user_name = ?, user_dept_id = ?, user_email = ?
                       WHERE token = ? OR token = ?""",
                    (new_name, new_org, new_email, token_hash, token)
                )
            if new_password:
                # A changed password must invalidate every other device: otherwise a
                # stolen session keeps working after the victim "secured" the account.
                # The current session is kept so the user is not logged out of the tab
                # they are using.
                cur.execute(
                    """DELETE FROM sessions
                       WHERE (user_id = ? OR user_name = ? OR user_name = ?)
                         AND token NOT IN (?, ?)""",
                    (user_id, cur_name, new_name, token or "", token_hash or "")
                )
                revoked["sessions"] = cur.rowcount if (cur.rowcount or 0) > 0 else 0
        transaction(_update)
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": f"정보 수정 실패: {e}"})
        return

    is_adm = bool(user_row["is_admin"])
    from services.auth import get_user_role
    user_role = get_user_role(user_row)
    access_log(ip, "account_update_profile", 200, f"{cur_name} -> {new_name}|{new_org}")

    # 소속 변경 요청은 관리자에게 승인 요청 알림으로 전달한다 (즉시 반영하지 않음).
    if dept_change_pending:
        try:
            from services.notification_service import add_notification
            add_notification(
                recipient_email="",
                recipient_name="관리자",
                sender_name=cur_name or "사용자",
                notif_type="dept_change",
                title="부서 변경 승인 요청",
                content=(
                    f"{cur_name}님이 소속 변경을 요청했습니다: "
                    f"{cur_org or '(미지정)'} → {requested_org}. "
                    "설정 > 사용자 관리에서 소속을 변경한 뒤 요청을 처리해주세요."
                ),
                link_id=str(user_id),
                tag="승인요청",
                tag_type="info"
            )
        except Exception:
            pass

    from services.audit_logger import log_audit
    log_audit(
        session=session,
        ip=ip,
        action="USER_UPDATE_PROFILE",
        target_type="user",
        target_id=new_name,
        details={"old_name": cur_name, "new_name": new_name, "old_dept": cur_org, "new_dept": new_org,
                 "requested_dept": requested_org if dept_change_pending else None,
                 "dept_change_pending": dept_change_pending,
                 "password_changed": bool(new_password), "avatar_changed": new_avatar != cur_avatar,
                 "sessions_revoked": revoked["sessions"]}
    )

    if dept_change_pending:
        message = (
            f"소속 변경({cur_org or '미지정'} → {requested_org}) 요청이 관리자에게 전달되었습니다. "
            "관리자 승인 후 반영됩니다."
        )
    elif new_password and revoked["sessions"]:
        message = (
            "회원 정보가 성공적으로 수정되었습니다. "
            f"비밀번호가 변경되어 다른 기기의 로그인 {revoked['sessions']}건이 만료되었습니다."
        )
    else:
        message = "회원 정보가 성공적으로 수정되었습니다."

    handler._send_json(200, {
        "ok": True,
        "message": message,
        "deptChangePending": dept_change_pending,
        "requestedOrg": requested_org if dept_change_pending else None,
        "passwordChanged": bool(new_password),
        "sessionsRevoked": revoked["sessions"],
        "user": {
            "name": new_name,
            "username": user_row.get("username") or new_name,
            "org": new_org,
            "department": new_org,
            "email": new_email,
            "avatarUrl": new_avatar,
            "isAdmin": is_adm,
            "role": user_role
        }
    })


# ---- /api/account/me (GET) — 현재 쿠키 세션 기반 사용자 프로필 확인 ----
def handle_account_me(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    token = handler._extract_token() if hasattr(handler, "_extract_token") else None
    name = session.get("name", "")
    org = session.get("org", "")
    email = session.get("email", "")
    is_adm = is_admin_user(session)

    # Fetch user row from DB for complete profile
    user_row = get_one("SELECT * FROM users WHERE name = ? AND dept_id = ? LIMIT 1", (name, org))
    username = (user_row.get("username") if user_row else None) or name
    avatar_url = (user_row.get("avatar_url") if user_row else "") or ""

    from services.auth import get_user_role
    user_role = get_user_role(user_row or session)

    from middleware_security import generate_csrf_token
    csrf_token = generate_csrf_token(token) if token else ""
    extra = [("Set-Cookie", f"argos_csrf={csrf_token}; Path=/; SameSite=Lax; Max-Age=86400")] if csrf_token else []

    handler._send_json(200, {
        "ok": True,
        "csrfToken": csrf_token,
        "user": {
            "name": name,
            "username": username,
            "org": org,
            "department": org,
            "email": email,
            "avatarUrl": avatar_url,
            "isAdmin": is_adm,
            "role": user_role
        }
    }, extra_headers=extra)


# ---- /api/account/csrf (GET) — CSRF 토큰 발급/갱신 ----
def handle_account_csrf(handler, parsed, ip):
    token = handler._extract_token() if hasattr(handler, "_extract_token") else None
    if not token:
        handler._send_json(401, {"ok": False, "error": "인증 세션이 없습니다."})
        return
    from middleware_security import generate_csrf_token
    csrf_token = generate_csrf_token(token)
    extra = [("Set-Cookie", f"argos_csrf={csrf_token}; Path=/; SameSite=Lax; Max-Age=86400")]
    handler._send_json(200, {
        "ok": True,
        "csrfToken": csrf_token
    }, extra_headers=extra)


