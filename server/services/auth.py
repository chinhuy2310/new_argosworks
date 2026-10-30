"""auth.py — 인증·세션 관리 (SQLite 버전)
기존 JSON 파일(accounts.json, sessions.json) 대신 SQLite DB를 사용한다.
모든 함수 시그니처와 반환 형식은 100% 유지된다.
"""
import hashlib
import hmac
import re
import secrets
import threading
import os
import time

from db import query, get_one, execute, transaction

PBKDF2_ROUNDS = 600000

# 테스트/벤치마크 환경에서만 반복 횟수를 낮출 수 있도록 허용한다.
# 운영 기본값은 항상 PBKDF2_ROUNDS(600,000)이며, 하한선(1,000) 미만은 무시한다.
MIN_PBKDF2_ROUNDS = 1000
MAX_PBKDF2_ROUNDS = 10000000


def _effective_pbkdf2_rounds():
    """ARGOS_PBKDF2_ROUNDS 환경변수가 유효하면 그 값을, 아니면 운영 기본값을 반환한다."""
    raw = (os.environ.get("ARGOS_PBKDF2_ROUNDS") or "").strip()
    if raw:
        try:
            value = int(raw)
            if MIN_PBKDF2_ROUNDS <= value <= MAX_PBKDF2_ROUNDS:
                return value
        except Exception:
            pass
    return PBKDF2_ROUNDS


from app_paths import APP_HOME
from utils.logging import log_line

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = APP_HOME


def account_key(name, org):
    """계정 복합 키 (기존 호환)."""
    return (name or "").strip() + "|" + (org or "").strip()


def read_accounts():
    """모든 계정을 반환한다. 기존 API 호환: dict keyed by 'name|org'."""
    rows = query("SELECT id, name, username, dept_id, email, salt, password_hash, is_admin, role, disabled, status, created_at FROM users")
    result = {}
    for r in rows:
        key = account_key(r["name"], r["dept_id"])
        result[key] = {
            "id": r["id"],
            "name": r["name"],
            "username": r.get("username") or r["name"],
            "org": r["dept_id"],
            "email": r["email"],
            "salt": r["salt"],
            "hash": r["password_hash"],
            "isAdmin": bool(r.get("is_admin")),
            "role": r.get("role") or "member",
            "disabled": r.get("disabled") or 0,
            "status": r.get("status") or "active",
            "createdAt": r["created_at"],
        }
    return result


def get_user_by_id(user_id):
    """ID로 단일 사용자를 조회한다 (인덱스 활용)."""
    if not user_id:
        return None
    return get_one(
        """SELECT id, name, username, dept_id, email, salt, password_hash, is_admin, role, disabled, status, created_at
           FROM users WHERE id = ? LIMIT 1""",
        (user_id,)
    )


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


def validate_username_format(username):
    """
    사용자 아이디(username) 형식을 검증한다.
    - 길이 3~30자
    - 영문 대소문자, 숫자, 특수문자(_ . -)만 허용
    - @는 이메일과의 혼동 방지를 위해 불허
    """
    username = (username or "").strip()
    if not username:
        raise ValueError("아이디(Username)를 입력해주세요.")
    if "@" in username or not USERNAME_RE.match(username):
        raise ValueError("아이디는 3~30자의 영문, 숫자, 특수문자(_ . -)만 사용 가능하며 @는 포함할 수 없습니다.")
    return username


def get_user_by_login(login_id, org=None):
    """
    로그인 식별자(아이디, 이메일, 사원명)로 사용자를 고속 조회한다 (인덱스 활용).
    전체 테이블을 메모리에 풀스캔하지 않고 DB 인덱스로 직접 조회한다.
    """
    login_id = (login_id or "").strip()
    if not login_id:
        return None
    login_lower = login_id.lower()

    # 1. username 매칭 (대소문자 무시)
    row = get_one(
        """SELECT id, name, username, dept_id, email, salt, password_hash, iterations, avatar_url,
                  is_admin, role, disabled, status, created_at
           FROM users
           WHERE LOWER(username) = ?
           ORDER BY id ASC
           LIMIT 1""",
        (login_lower,)
    )
    if row:
        return row

    # 2. email 매칭 (대소문자 무시)
    row = get_one(
        """SELECT id, name, username, dept_id, email, salt, password_hash, iterations, avatar_url,
                  is_admin, role, disabled, status, created_at
           FROM users
           WHERE email != '' AND LOWER(email) = ?
           ORDER BY id ASC
           LIMIT 1""",
        (login_lower,)
    )
    if row:
        return row

    # 3. 소속 부서 + 이름 매칭 (동명이인 방지를 위해 부서가 지정된 경우만 허용)
    if org:
        row = get_one(
            """SELECT id, name, username, dept_id, email, salt, password_hash, iterations, avatar_url,
                      is_admin, role, disabled, status, created_at
               FROM users
               WHERE LOWER(name) = ? AND LOWER(dept_id) = ?
               ORDER BY id ASC
               LIMIT 1""",
            (login_lower, str(org).strip().lower())
        )
        if row:
            return row

    # 부서 지정 없는 사원명 단독 매칭은 타 부서 동명이인의 계정 탈취 및 권한 상승을 방지하기 위해 불허
    return None


def create_user(name, username, org, email, salt, hash_pwd, role="member", is_admin=False, status="active", disabled=0, hash_algo="pbkdf2_sha256", iterations=None):
    """
    단일 사용자를 원자적(Atomic)으로 생성한다.
    동시성 요청 시 Race Condition 및 중복 username/email을 DB 제약조건과 함께 안전하게 방어한다.
    """
    name = (name or "").strip()
    username = (username or name).strip()
    org = (org or "").strip()
    email = (email or "").strip()

    if username != name:
        username = validate_username_format(username)
    elif "@" in username:
        raise ValueError("아이디에는 @를 포함할 수 없습니다.")

    if iterations is None:
        iterations = _effective_pbkdf2_rounds()

    if not name:
        raise ValueError("이름(Name)을 입력해주세요.")

    # 1. 중복 username 검증
    dup_user = get_one("SELECT id, status FROM users WHERE LOWER(username) = LOWER(?) ORDER BY id ASC LIMIT 1", (username,))
    if dup_user:
        if (dup_user.get("status") or "").lower() == "pending":
            raise ValueError("해당 ID는 이미 계정 발급 승인 요청되어 관리자 승인 대기(Pending) 중입니다.")
        raise ValueError("이미 등록된 ArgosWorks ID입니다. 다른 ID를 입력하거나 로그인해주세요.")

    # 2. 중복 email 검증 (email이 제공된 경우)
    if email:
        dup_email = get_one("SELECT id, status FROM users WHERE email != '' AND LOWER(email) = LOWER(?) ORDER BY id ASC LIMIT 1", (email,))
        if dup_email:
            if (dup_email.get("status") or "").lower() == "pending":
                raise ValueError("해당 이메일로 이미 계정 발급 승인 요청되어 관리자 승인 대기(Pending) 중입니다.")
            raise ValueError("이미 등록된 이메일 주소입니다. 다른 이메일을 입력하거나 로그인해주세요.")

    # 3. 동일 소속 + 이름 중복 검증
    dup_name_dept = get_one("SELECT id, status FROM users WHERE name = ? AND dept_id = ? ORDER BY id ASC LIMIT 1", (name, org))
    if dup_name_dept:
        if (dup_name_dept.get("status") or "").lower() == "pending":
            raise ValueError("해당 소속에 동일한 이름으로 계정 발급 승인 요청이 이미 접수되어 대기 중입니다.")
        raise ValueError("해당 소속에 이미 동일한 이름의 사용자가 존재합니다.")

    from datetime import datetime
    now_iso = datetime.now().isoformat()

    def _insert(conn):
        cur = conn.cursor()
        if org:
            dept_exists = cur.execute("SELECT 1 FROM departments WHERE id = ?", (org,)).fetchone()
            if not dept_exists:
                cur.execute(
                    "INSERT OR IGNORE INTO departments(id, name, color_index) VALUES (?, ?, 1)",
                    (org, org)
                )
        cur.execute(
            """INSERT INTO users(name, username, dept_id, email, salt, password_hash, is_admin, role, disabled, status, created_at, hash_algo, iterations)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, username, org, email, salt, hash_pwd, 1 if is_admin else 0, role, disabled, status, now_iso, hash_algo, iterations)
        )

    transaction(_insert)
    return get_user_by_login(username)


def safe_delete_user(user_id):
    """
    사용자를 안전하게 삭제한다:
    - 외래키 제약조건 위반(ForeignKeyViolation) 및 고아 FK 방지를 위해
      records.assignee_id 및 schedule_events.owner_id를 동일 트랜잭션에서 NULL 처리.
    - 해당 사용자의 세션 및 일정 참여자 목록 정리 후 사용자 삭제.
    """
    user = get_one("SELECT * FROM users WHERE id = ? LIMIT 1", (user_id,))
    if not user:
        return False
    user_name = user.get("name", "")
    user_dept = user.get("dept_id", "")

    def _do_del(conn):
        cur = conn.cursor()
        # 1. 업무 카드 assignee_id NULL 처리 (고아 FK 방지)
        cur.execute("UPDATE records SET assignee_id = NULL WHERE assignee_id = ?", (user_id,))
        # 2. 일정 소유자 owner_id NULL 처리
        cur.execute("UPDATE schedule_events SET owner_id = NULL WHERE owner_id = ?", (user_id,))
        # 3. 일정 참여자 항목 정리
        cur.execute("DELETE FROM schedule_participants WHERE user_name = ?", (user_name,))
        # 4. 세션 만료
        cur.execute("DELETE FROM sessions WHERE user_name = ? AND user_dept_id = ?", (user_name, user_dept))
        # 5. 사용자 삭제
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))

    transaction(_do_del)
    return True


def write_accounts(accounts):
    """계정 목록을 갱신한다 (기존 API 호환). 동시성 데이터 유실을 방지하기 위해 일괄 DELETE를 수행하지 않는다."""
    def _do(conn):
        cur = conn.cursor()
        existing = {}
        for row in cur.execute("SELECT id, name, dept_id FROM users").fetchall():
            uid = row["id"] if isinstance(row, dict) else row[0]
            uname = row["name"] if isinstance(row, dict) else row[1]
            udept = row["dept_id"] if isinstance(row, dict) else row[2]
            existing[account_key(uname, udept)] = uid

        for key, acc in accounts.items():
            name = acc.get("name", "")
            username = acc.get("username") or name
            org = acc.get("org", "")
            akey = account_key(name, org)

            if akey in existing:
                cur.execute(
                    """UPDATE users SET username=?, email=?, salt=?, password_hash=?, created_at=?
                       WHERE id=?""",
                    (username, acc.get("email", ""), acc.get("salt", ""),
                     acc.get("hash", ""), acc.get("createdAt", ""),
                     existing[akey])
                )
            else:
                dept_id = org
                if dept_id:
                    dept_exists = cur.execute(
                        "SELECT 1 FROM departments WHERE id = ?", (dept_id,)
                    ).fetchone()
                    if not dept_exists:
                        cur.execute(
                            "INSERT OR IGNORE INTO departments(id, name, color_index) VALUES (?, ?, 1)",
                            (dept_id, dept_id)
                        )
                is_adm = 1 if (acc.get("isAdmin") or acc.get("is_admin")) else 0
                role = "admin" if is_adm else acc.get("role", "member")
                status = "active" if is_adm else acc.get("status", "pending")
                disabled = 0 if is_adm else acc.get("disabled", 1)
                cur.execute(
                    """INSERT INTO users(name, username, dept_id, email, salt, password_hash, is_admin, role, disabled, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, username, dept_id, acc.get("email", ""), acc.get("salt", ""),
                     acc.get("hash", ""), is_adm, role, disabled, status, acc.get("createdAt", ""))
                )

    transaction(_do)


def hash_password(password, salt_hex=None, iterations=None):
    """PBKDF2 비밀번호 해싱 (기본 600,000회 반복)."""
    if iterations is None:
        iterations = _effective_pbkdf2_rounds()
    salt = os.urandom(16) if salt_hex is None else bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iterations)
    return salt.hex(), digest.hex()


def verify_password(password, salt_hex, hash_hex, iterations=None, user_id=None):
    """
    비밀번호 검증 및 자동 점진적 보안 업그레이드(Auto-upgrade hash to 600k iterations).
    단일 반복 횟수로 검증하여 잘못된 비밀번호 시 CPU 낭비(DoS 위험)를 방지한다.
    """
    if not salt_hex or not hash_hex:
        return False

    effective_rounds = _effective_pbkdf2_rounds()

    target_iters = iterations
    if not target_iters and user_id:
        try:
            row = get_one("SELECT iterations FROM users WHERE id = ? LIMIT 1", (user_id,))
            if row and row.get("iterations"):
                target_iters = int(row["iterations"])
        except Exception:
            pass

    if target_iters:
        try:
            _, digest_hex = hash_password(password, salt_hex, iterations=target_iters)
            if hmac.compare_digest(digest_hex, hash_hex):
                # 업그레이드 목표는 항상 운영 기준(PBKDF2_ROUNDS)이다.
                if target_iters < PBKDF2_ROUNDS and user_id:
                    try:
                        new_salt, new_hash = hash_password(password, iterations=PBKDF2_ROUNDS)
                        execute(
                            "UPDATE users SET salt = ?, password_hash = ?, iterations = ?, hash_algo = 'pbkdf2_sha256' WHERE id = ?",
                            (new_salt, new_hash, PBKDF2_ROUNDS, user_id)
                        )
                    except Exception:
                        pass
                return True
        except Exception:
            return False
        return False

    try:
        _, digest_hex = hash_password(password, salt_hex, iterations=effective_rounds)
        if hmac.compare_digest(digest_hex, hash_hex):
            return True
    except Exception:
        pass

    if effective_rounds != 100000:
        try:
            _, digest_hex_100k = hash_password(password, salt_hex, iterations=100000)
            if hmac.compare_digest(digest_hex_100k, hash_hex):
                if user_id:
                    try:
                        new_salt, new_hash = hash_password(password, iterations=PBKDF2_ROUNDS)
                        execute(
                            "UPDATE users SET salt = ?, password_hash = ?, iterations = ?, hash_algo = 'pbkdf2_sha256' WHERE id = ?",
                            (new_salt, new_hash, PBKDF2_ROUNDS, user_id)
                        )
                    except Exception:
                        pass
                return True
        except Exception:
            pass

    return False

def get_user_role(user_or_session):
    """
    사용자의 시스템 권한 등급을 반환한다 ('admin', 'manager', 'member', 'viewer').
    Single Source of Truth: 'role' 컬럼을 표준으로 하여 권한 모순을 방지한다.
    """
    if not user_or_session:
        return "viewer"
    if isinstance(user_or_session, dict):
        # 1. Look up by verified user ID in DB if available
        u_id = user_or_session.get("id") or user_or_session.get("user_id")
        if u_id:
            row = get_one("SELECT role, is_admin FROM users WHERE id = ? LIMIT 1", (u_id,))
            if row:
                r = row.get("role")
                if r in ("admin", "manager", "member", "viewer"):
                    return r
                if row.get("is_admin") == 1:
                    return "admin"
                return "member"

        # 2. Look up by verified username in DB if available
        username = user_or_session.get("username")
        if username:
            row = get_one("SELECT role, is_admin FROM users WHERE username != '' AND LOWER(username) = LOWER(?) ORDER BY id ASC LIMIT 1", (username,))
            if row:
                r = row.get("role")
                if r in ("admin", "manager", "member", "viewer"):
                    return r
                if row.get("is_admin") == 1:
                    return "admin"
                return "member"

        # 3. Session dictionary fallback
        role = user_or_session.get("role")
        if role in ("admin", "manager", "member", "viewer"):
            return role
        if user_or_session.get("isAdmin") or user_or_session.get("is_admin"):
            return "admin"
        if user_or_session.get("isManager"):
            return "manager"
        return "member"

    # Numeric user_id
    if isinstance(user_or_session, int) or (isinstance(user_or_session, str) and user_or_session.isdigit()):
        row = get_one("SELECT role, is_admin FROM users WHERE id = ? LIMIT 1", (int(user_or_session),))
        if row:
            r = row.get("role")
            if r in ("admin", "manager", "member", "viewer"):
                return r
            if row.get("is_admin") == 1:
                return "admin"
            return "member"

    # String username
    if isinstance(user_or_session, str):
        login_str = user_or_session.strip()
        if login_str:
            row = get_one("SELECT role, is_admin FROM users WHERE username != '' AND LOWER(username) = LOWER(?) ORDER BY id ASC LIMIT 1", (login_str,))
            if row:
                r = row.get("role")
                if r in ("admin", "manager", "member", "viewer"):
                    return r
                if row.get("is_admin") == 1:
                    return "admin"
                return "member"

    return "member"


def is_admin_user(user_or_session, email=None):
    """
    사용자가 Admin 권한을 가지고 있는지 검증한다.
    Single Source of Truth: get_user_role(user_or_session) == 'admin'.
    """
    if not user_or_session:
        return False
    return get_user_role(user_or_session) == "admin"

def is_manager_or_admin(user_or_session):
    """사용자가 Manager(부서장) 이상(Admin/Master 포함)의 관리 권한을 가지고 있는지 판정한다."""
    if is_admin_user(user_or_session):
        return True
    role = get_user_role(user_or_session)
    return role in ("admin", "manager")


def can_view_record(user_or_session, record):
    """
    레코드 열람 권한 판정:
    - admin: 모든 레코드 열람 가능
    - is_private == 1: 작성자, 담당자, 부서장(manager), admin만 열람 가능
    - manager: 자기 부서 전체 + 타 부서의 일반 공개 레코드 열람 가능
    - member / viewer: 자기 부서 레코드 또는 본인이 담당자/참여자로 지정된 레코드 열람 가능
    (보안 강화: 동명이인 타 부서 충돌 방지 및 정확한 식별자 매칭)
    """
    if not user_or_session:
        return False
    role = get_user_role(user_or_session)
    if role == "admin":
        return True

    u_id = user_or_session.get("id") or user_or_session.get("user_id")
    u_name = user_or_session.get("name", "").strip().lower()
    u_username = user_or_session.get("username", "").strip().lower()
    u_email = user_or_session.get("email", "").strip().lower()
    u_dept = (user_or_session.get("org") or user_or_session.get("dept_id") or "").strip().lower()

    rec_dept = (record.get("dept_id") or record.get("org") or "").strip().lower()
    rec_assignee_id = record.get("assignee_id")
    rec_assignee = (record.get("assignee_name") or record.get("assignee") or "").strip().lower()
    rec_assignee_email = (record.get("assignee_email") or "").strip().lower()
    
    raw_participants = record.get("participants") or ""
    parts = [p.strip().lower() for p in re.split(r"[,;/\n]+", str(raw_participants)) if p.strip()]

    is_same_dept = bool(u_dept and u_dept == rec_dept)
    is_private = bool(record.get("is_private"))

    # 정확한 담당자/참여자 매칭:
    # 비공개 레코드(is_private=1)는 동명이인 타 부서 유출 방지를 위해 이름 단독 매칭 시 동일 부서 필수 검증
    is_involved = False
    if u_id and rec_assignee_id and str(u_id) == str(rec_assignee_id):
        is_involved = True
    elif u_email and rec_assignee_email and u_email == rec_assignee_email:
        is_involved = True
    elif u_name and u_name == rec_assignee:
        if not is_private or is_same_dept or not rec_dept:
            is_involved = True
    elif u_username and u_username in parts:
        if not is_private or is_same_dept or not rec_dept:
            is_involved = True
    elif u_name and u_name in parts:
        if not is_private or is_same_dept or not rec_dept:
            is_involved = True

    is_same_dept = bool(u_dept and u_dept == rec_dept)
    is_private = bool(record.get("is_private"))

    if is_private:
        if is_involved:
            return True
        if is_same_dept and role == "manager":
            return True
        return False

    if is_same_dept:
        return True
    if is_involved:
        return True
    if role == "manager":
        return True

    return False

def can_modify_record(user_or_session, record):
    """
    레코드 수정/삭제 권한 판정:
    - viewer는 읽기 전용 역할로 무조건 차단 (403)
    - admin은 전체 수정 가능
    - manager는 자기 부서 레코드 수정 가능
    - member는 자신이 담당자인 레코드만 수정 가능 (동명이인 타 부서 격리)
    """
    if not user_or_session:
        return False
    role = get_user_role(user_or_session)
    if role == "admin":
        return True
    if role == "viewer":
        return False

    u_id = user_or_session.get("id") or user_or_session.get("user_id")
    u_name = user_or_session.get("name", "").strip().lower()
    u_username = user_or_session.get("username", "").strip().lower()
    u_dept = (user_or_session.get("org") or user_or_session.get("dept_id") or "").strip().lower()

    rec_dept = (record.get("dept_id") or record.get("org") or "").strip().lower()
    rec_assignee_id = record.get("assignee_id")
    rec_assignee = (record.get("assignee_name") or record.get("assignee") or "").strip().lower()

    if role == "manager" and u_dept and rec_dept and u_dept == rec_dept:
        return True
    if u_id and rec_assignee_id:
        if str(u_id) == str(rec_assignee_id):
            return True
    elif u_name and u_name == rec_assignee:
        is_private = bool(record.get("is_private"))
        if not is_private or u_dept == rec_dept or not rec_dept:
            return True

    return False

def can_delete_record(user_or_session, record):
    """
    레코드 삭제 권한 판정 (기업 거버넌스 엄격 적용 - Phương án A):
    - admin: 전체 레코드 삭제 가능
    - manager: 자기 부서 레코드만 삭제 가능
    - member / viewer: 삭제 절대 불가 (403 차단)
    """
    if not user_or_session:
        return False
    role = get_user_role(user_or_session)
    if role == "admin":
        return True
    if role == "manager":
        u_dept = (user_or_session.get("org") or user_or_session.get("dept_id") or "").strip().lower()
        rec_dept = (record.get("dept_id") or record.get("org") or "").strip().lower()
        if u_dept and rec_dept and u_dept == rec_dept:
            return True
    return False


def can_transition_status(user_or_session, record, target_status):
    """
    상태 전이 권한 검증:
    - viewer는 어떠한 상태 변경도 불가
    - admin은 모든 상태로 변경 가능 (완료 포함)
    - manager는 자기 부서 레코드에 대해 모든 상태로 변경 가능 (완료 포함)
    - member는 '검토'(Review)까지만 변경 가능하며, '완료'(Done/Closed/Resolved)는 관리자만 가능
    """
    if not user_or_session:
        return False, "인증 세션이 없습니다."

    if not can_modify_record(user_or_session, record):
        return False, "해당 업무 카드의 상태를 변경할 권한이 없습니다."

    role = get_user_role(user_or_session)
    clean_target = (target_status or "").strip().lower()
    is_done = clean_target in ("완료", "done", "closed", "resolved", "완료됨")

    if is_done:
        if role == "admin":
            return True, ""
        if role == "manager":
            u_dept = (user_or_session.get("org") or user_or_session.get("dept_id") or "").strip().lower()
            rec_dept = (record.get("dept_id") or record.get("org") or "").strip().lower()
            if u_dept and rec_dept and u_dept == rec_dept:
                return True, ""
            return False, "타 부서의 작업 카드는 해당 부서 관리자 또는 시스템 관리자만 완료할 수 있습니다."
        return False, "일반 사용자는 '완료' 상태로 직접 변경할 수 없습니다. '검토' 상태로 변경하여 관리자 승인을 요청해 주세요."

    return True, ""

def is_viewer(user_or_session):
    """Viewer là role chỉ đọc: không được thực hiện bất kỳ thay đổi dữ liệu nào."""
    return bool(user_or_session) and get_user_role(user_or_session) == "viewer"


def can_write_data(user_or_session):
    """Mọi thao tác ghi dữ liệu yêu cầu user đã đăng nhập và KHÔNG phải viewer."""
    if not user_or_session:
        return False
    return get_user_role(user_or_session) != "viewer"


def check_record_write_access(user_or_session, record):
    """
    Kiểm tra quyền ghi trên MỘT record cụ thể.
    Dùng chung cho các endpoint từng thiếu kiểm tra (assign/unassign lịch,
    upload attachment, push Jira) để tránh lặp lại lỗi "quên check".
    Trả về (ok, error_message).
    """
    if not user_or_session:
        return False, "인증 세션이 필요합니다."
    if not can_write_data(user_or_session):
        return False, "조회 전용(Viewer) 권한의 사용자는 데이터를 변경할 수 없습니다."
    if not can_modify_record(user_or_session, record):
        return False, "해당 업무 카드를 변경할 권한이 없습니다."
    return True, ""


def is_display_name_unique(name):
    """
    같은 표시 이름(name)을 가진 계정이 시스템에 1개뿐인지 확인한다.

    알림(notifications)과 채팅 세션은 이메일이 없을 때 표시 이름으로 대상을
    찾는데, 이름은 부서가 달라도 중복될 수 있다(schema 상 unique 제약 없음).
    이름 단독 매칭은 동명이인 간 데이터 노출로 이어지므로, 이름이 유일할 때만
    매칭을 허용하는 fail-closed 가드로 사용한다.
    """
    clean = (name or "").strip()
    if not clean:
        return False
    try:
        row = get_one("SELECT COUNT(*) AS c FROM users WHERE LOWER(name) = LOWER(?)", (clean,))
    except Exception:
        return False
    if not row:
        return False
    return int(row.get("c") or 0) == 1


def user_can_access_notification(user_or_session, notification):
    """Notification có thuộc về user hiện tại không (chống IDOR).

    이름 기반 매칭은 동명이인이 존재하면 사용하지 않는다(타 사용자 알림 조작 방지).
    """
    if not user_or_session or not notification:
        return False
    from utils.text import assignee_base_name

    email = (user_or_session.get("email") or "").strip().lower()
    name = (user_or_session.get("name") or "").strip()
    base = assignee_base_name(name) if name else ""
    r_email = (notification.get("recipient_email") or "").strip().lower()
    r_name = (notification.get("recipient_name") or "").strip()

    # Thông báo broadcast cho toàn hệ thống
    if r_email == "all" or (r_email == "" and r_name in ("", "all")):
        return True
    if email and r_email == email:
        return True
    if is_admin_user(user_or_session) and r_name in ("관리자", "admin"):
        return True
    if not is_display_name_unique(name):
        return False
    if name and r_name == name:
        return True
    if base and r_name == base:
        return True
    return False


def visible_records(session, records=None):
    """
    단일 권한 진실의 원천 (Single Source of Truth).
    N+1 쿼리 방지: role을 1회만 계산하고 모든 레코드 필터링에 재사용한다.
    """
    if not session:
        return []
    if records is None:
        from services.data_store import read_records
        records = read_records()
    if is_admin_user(session):
        return list(records)
    role = get_user_role(session)
    sess_cached = dict(session)
    sess_cached["role"] = role
    return [r for r in records if can_view_record(sess_cached, r)]


# ---------------------------------------------------------------------------
# 일정(schedule_events) 열람 권한 — REST API와 AI 챗봇 도구가 공유하는 단일 기준
# ---------------------------------------------------------------------------
def build_user_dept_map():
    """사원-부서 맵(이름 정규화 기준)을 구성한다. 일정 RBAC 및 이름 정규화 공통 기준."""
    from utils.text import assignee_base_name

    mapping = {}
    try:
        for u in query(
            "SELECT name, dept_id, email FROM users "
            "WHERE disabled = 0 AND (status IS NULL OR status = 'active')"
        ):
            bn = assignee_base_name(u.get("name", "")).strip().lower()
            if bn:
                mapping[bn] = {
                    "name": (u.get("name") or "").strip(),
                    "org": (u.get("dept_id") or "lab").strip(),
                    "email": (u.get("email") or "").strip(),
                }
    except Exception:
        pass
    return mapping


def _schedule_event_matches(user_or_session, event, user_dept_map, user_name, user_dept):
    """(비관리자 기준) 일정 1건의 열람 가능 여부 — 부서/본인/참여자 규칙."""
    from utils.text import assignee_base_name

    ev_owner = (event.get("ownerName") or event.get("assignee") or "").strip()
    ev_org = (
        event.get("ownerOrg") or event.get("org") or event.get("dept_id") or ""
    ).strip().lower()
    if not ev_org and ev_owner:
        info = (user_dept_map or {}).get(assignee_base_name(ev_owner).lower()) or {}
        ev_org = (info.get("org") or "").strip().lower()

    if user_dept and ev_org and ev_org == user_dept:
        return True
    if ev_owner and user_name and ev_owner == user_name:
        return True

    for p in (event.get("participants") or []):
        if isinstance(p, dict):
            p_name = (p.get("name") or "").strip()
            p_org = (p.get("org") or "").strip().lower()
            if p_name and user_name and p_name == user_name:
                return True
            if user_dept and p_org and p_org == user_dept:
                return True
        elif p and user_name and str(p).strip() == user_name:
            return True
    return False


def can_view_schedule_event(user_or_session, event, user_dept_map=None):
    """일정 1건 열람 권한: admin 전체 / 같은 부서 / 본인 일정 / 본인이 참여자."""
    if not user_or_session or not event:
        return False
    if is_admin_user(user_or_session) or get_user_role(user_or_session) == "admin":
        return True
    if user_dept_map is None:
        user_dept_map = build_user_dept_map()
    user_dept = (user_or_session.get("org") or user_or_session.get("dept_id") or "").strip().lower()
    user_name = (user_or_session.get("name") or "").strip()
    return _schedule_event_matches(user_or_session, event, user_dept_map, user_name, user_dept)


def visible_schedule_events(session, events=None, user_dept_map=None):
    """
    일정 목록 열람 권한 필터 (단일 진실의 원천).
    admin은 전체, 그 외에는 본인 부서 일정/본인 일정/본인 참여 일정만 반환한다.
    """
    if not session:
        return []
    if events is None:
        from services.data_store import read_schedule
        events = read_schedule()
    if is_admin_user(session) or get_user_role(session) == "admin":
        return list(events)
    if user_dept_map is None:
        user_dept_map = build_user_dept_map()
    user_dept = (session.get("org") or session.get("dept_id") or "").strip().lower()
    user_name = (session.get("name") or "").strip()
    return [
        e for e in events
        if _schedule_event_matches(session, e, user_dept_map, user_name, user_dept)
    ]


# ---------------------------------------------------------------------------
# 검색 결과 / 상세 화면 RBAC — "탐색(목록)"과 "상세(엔드포인트)"가 같은 기준을 쓰도록 통일
# ---------------------------------------------------------------------------
def resolve_record_by_key(key, cfg=None):
    """업무 코드·이슈 키·레코드 ID로 레코드 1건을 조회한다 (로컬 → Jira 캐시 순)."""
    if key is None:
        return None
    clean = str(key).strip().lstrip("#").upper()
    if not clean:
        return None

    from services.data_store import find_record_by_key_or_code
    try:
        rec = find_record_by_key_or_code(clean)
    except Exception:
        rec = None
    if rec:
        return rec

    try:
        from services.data_store import read_records
        for r in read_records():
            jk = ((r.get("jira") or {}).get("key") or "").strip().upper()
            cc = (r.get("cardCode") or "").strip().upper()
            rid = str(r.get("id") or "").strip().upper()
            if clean in (jk, cc, rid):
                return r
    except Exception:
        pass

    if cfg:
        try:
            from services.jira_client import get_cached_jira_records
            for r in (get_cached_jira_records(cfg).get("records") or []):
                jk = ((r.get("jira") or {}).get("key") or "").strip().upper()
                cc = (r.get("cardCode") or "").strip().upper()
                rid = str(r.get("id") or "").replace("jira-", "").strip().upper()
                if clean in (jk, cc, rid):
                    return r
        except Exception:
            pass
    return None


_NO_ASSIGNEE_VALUES = ("미배정", "unassigned", "none", "-", "")


def _split_participants(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        out = []
        for p in raw:
            name = (p.get("name") or "").strip() if isinstance(p, dict) else str(p).strip()
            if name:
                out.append(name)
        return out
    return [p.strip() for p in re.split(r"[,;/\n]+", str(raw)) if p.strip()]


def filter_issue_payload_by_permission(session, issue, cfg=None):
    """
    이슈 상세 payload에서 사용자가 열람할 수 없는 하위 작업/상위 작업/참여자 정보를 제거한다.

    - admin: 원본 그대로 반환 (전체 열람 권한)
    - 하위 작업(subtasks / subtasksDetail): 권한 없는 항목 제거 (식별 불가 시 fail-closed)
    - 상위 작업(parentSummary): 권한이 없으면 제거
    - 참여자(contributor*) : 남은 하위 작업 기준으로 재계산
    """
    if not session or not isinstance(issue, dict):
        return issue
    if is_admin_user(session) or get_user_role(session) == "admin":
        return issue

    def _can_view_key(k):
        rec = resolve_record_by_key(k, cfg=cfg)
        return bool(rec) and can_view_record(session, rec)

    subtasks_detail = issue.get("subtasksDetail")
    if isinstance(subtasks_detail, list):
        issue["subtasksDetail"] = [
            st for st in subtasks_detail
            if (st or {}).get("key") and _can_view_key(st.get("key"))
        ]

    subtasks = issue.get("subtasks")
    if isinstance(subtasks, list):
        issue["subtasks"] = [k for k in subtasks if _can_view_key(k)]

    parent_key = issue.get("parentKey") or (issue.get("jira") or {}).get("parentKey")
    if parent_key and issue.get("parentSummary") and not _can_view_key(parent_key):
        issue["parentSummary"] = ""

    # 참여자(기여자) 재계산 — 제거된 하위 작업의 담당자가 남지 않도록 한다
    contrib = {}
    main_assignee = str(issue.get("assignee") or "").strip()
    if main_assignee.lower() not in _NO_ASSIGNEE_VALUES:
        contrib[main_assignee] = 0
    for p in _split_participants(issue.get("participants")):
        if p.lower() not in _NO_ASSIGNEE_VALUES:
            contrib[p] = 0
    for st in (issue.get("subtasksDetail") or []):
        a = str(st.get("assignee") or "").strip()
        if a and a.lower() not in _NO_ASSIGNEE_VALUES:
            contrib[a] = contrib.get(a, 0) + 1
    if main_assignee in contrib and contrib[main_assignee] == 0:
        contrib[main_assignee] = 1
    ordered = sorted(contrib.items(), key=lambda x: x[1], reverse=True)
    issue["contributorMap"] = dict(ordered)
    issue["contributorNames"] = [k for k, _ in ordered]
    issue["allDescendantsCount"] = len(issue.get("subtasksDetail") or [])
    issue["hasSubtasks"] = bool(issue.get("subtasksDetail") or issue.get("subtasks"))
    return issue


def can_view_search_item(session, item):
    """검색 결과 1건(제품 / 일정 / 업무 카드)에 대한 열람 권한 판정."""
    if not session or not isinstance(item, dict):
        return False
    rid = str(item.get("id") or "")
    doc_id = str(item.get("doc_id") or "")
    if item.get("productLink") or rid.startswith(("product-", "pim-", "product:", "pim:")):
        return True
    if (rid.startswith(("schedule-", "schedule:"))
            or doc_id.startswith("schedule:")
            or item.get("ownerName") or item.get("ownerOrg")):
        return can_view_schedule_event(session, item)
    return can_view_record(session, item)


def can_view_pim_price(user_or_session):
    """PIM 제품 기준 가격 열람 권한: Admin 및 영업/경영 부서만 허용 (일반 엔지니어/타 부서에는 마스킹)"""
    if not user_or_session:
        return False
    role = get_user_role(user_or_session)
    if role == "admin":
        return True
    dept = (user_or_session.get("org") or user_or_session.get("dept_id") or "").lower()
    if dept in ("sales", "biz", "exec", "management", "경영", "영업"):
        return True
    return False


def can_modify_pim(user_or_session):
    """PIM 제품 및 가격 수정 권한: Admin 및 모든 부서장(Manager) 허용"""
    if not user_or_session:
        return False
    return is_manager_or_admin(user_or_session)


# ---------------------------------------------------------------------------
# 세션 관리 (SQLite sessions table) & 로그인 보안 제어
# ---------------------------------------------------------------------------
_session_lock = threading.Lock()
_login_failures_lock = threading.Lock()
_login_failures = {}  # key: "ip:user" -> [timestamp, timestamp, ...]

_DUMMY_SALT = "0" * 32
DEFAULT_SESSION_TTL_HOURS = 24
DEFAULT_SESSION_MAX_AGE_HOURS = 168

def get_session_ttl_seconds():
    """세션 유효 기간(초)을 반환한다 (환경변수 SESSION_TTL_HOURS 지원, 기본 24시간)."""
    try:
        val = int(os.environ.get("SESSION_TTL_HOURS", DEFAULT_SESSION_TTL_HOURS))
        return max(1, val) * 3600
    except Exception:
        return DEFAULT_SESSION_TTL_HOURS * 3600

def get_session_max_age_seconds():
    """세션 절대 유효 기간(초)을 반환한다 (환경변수 SESSION_MAX_AGE_HOURS 지원, 기본 168시간=7일)."""
    try:
        val = int(os.environ.get("SESSION_MAX_AGE_HOURS", DEFAULT_SESSION_MAX_AGE_HOURS))
        return max(1, val) * 3600
    except Exception:
        return DEFAULT_SESSION_MAX_AGE_HOURS * 3600

def check_login_rate_limit(ip, identifier, return_retry_after=False):
    """
    무차별 대입 공격(Brute-force) 3단계 방어:
    1. (IP, 계정): 15분 내 5회 실패 시 차단 (환경변수 LOGIN_MAX_FAILURES_PER_IP_USER, 기본 5)
    2. 계정 전역 (모든 IP): 15분 내 20회 실패 시 차단 (환경변수 LOGIN_MAX_FAILURES_PER_ACCOUNT, 기본 20)
    3. IP 전역 (모든 계정): 15분 내 30회 실패 시 차단 (환경변수 LOGIN_MAX_FAILURES_PER_IP, 기본 30)
    """
    now = time.time()
    cutoff = now - 900
    ident = (identifier or '').strip().lower()

    limit_ip_user = int(os.environ.get("LOGIN_MAX_FAILURES_PER_IP_USER", 5))
    limit_account = int(os.environ.get("LOGIN_MAX_FAILURES_PER_ACCOUNT", 20))
    limit_ip = int(os.environ.get("LOGIN_MAX_FAILURES_PER_IP", 30))

    try:
        # Tier 1: Target (IP, account)
        if ident and ip:
            row_ip_user = get_one(
                "SELECT COUNT(*) as cnt, MIN(failed_at) as earliest FROM login_attempts WHERE ip = ? AND identifier = ? AND failed_at > ?",
                (ip, ident, cutoff)
            )
            cnt_ip_user = row_ip_user["cnt"] if row_ip_user else 0
            if cnt_ip_user >= limit_ip_user:
                earliest = row_ip_user["earliest"] if row_ip_user and row_ip_user.get("earliest") else cutoff
                remaining = max(1, int(900 - (now - earliest)))
                mins = max(1, remaining // 60)
                msg = f"보안 경고: 해당 계정의 로그인 실패 횟수 초과로 임시 잠금되었습니다. {mins}분 후 다시 시도하세요."
                return (False, msg, remaining) if return_retry_after else (False, msg)

        # Tier 2: Account global across all IPs
        if ident:
            row_account = get_one(
                "SELECT COUNT(*) as cnt, MIN(failed_at) as earliest FROM login_attempts WHERE identifier = ? AND failed_at > ?",
                (ident, cutoff)
            )
            cnt_account = row_account["cnt"] if row_account else 0
            if cnt_account >= limit_account:
                earliest = row_account["earliest"] if row_account and row_account.get("earliest") else cutoff
                remaining = max(1, int(900 - (now - earliest)))
                mins = max(1, remaining // 60)
                msg = f"보안 경고: 해당 계정에 대한 비정상적인 로그인 시도가 감지되어 계정이 보호 잠금되었습니다. {mins}분 후 다시 시도하세요."
                return (False, msg, remaining) if return_retry_after else (False, msg)

        # Tier 3: IP global across all accounts
        if ip:
            row_ip = get_one(
                "SELECT COUNT(*) as cnt, MIN(failed_at) as earliest FROM login_attempts WHERE ip = ? AND failed_at > ?",
                (ip, cutoff)
            )
            cnt_ip = row_ip["cnt"] if row_ip else 0
            if cnt_ip >= limit_ip:
                earliest = row_ip["earliest"] if row_ip and row_ip.get("earliest") else cutoff
                remaining = max(1, int(900 - (now - earliest)))
                mins = max(1, remaining // 60)
                msg = f"보안 경고: 비정상적인 로그인 시도로 인해 IP가 임시 차단되었습니다. {mins}분 후 다시 시도하세요."
                return (False, msg, remaining) if return_retry_after else (False, msg)

    except Exception:
        key = f"{ip}:{ident}"
        with _login_failures_lock:
            attempts = [t for t in _login_failures.get(key, []) if now - t < 900]
            _login_failures[key] = attempts
            if len(attempts) >= limit_ip_user:
                remaining = max(1, int(900 - (now - attempts[0])))
                mins = max(1, remaining // 60)
                msg = f"보안 경고: 로그인 시도 실패 횟수 초과로 계정이 임시 잠금되었습니다. {mins}분 후 다시 시도하세요."
                return (False, msg, remaining) if return_retry_after else (False, msg)

    return (True, "", 0) if return_retry_after else (True, "")

def record_login_failure(ip, identifier):
    """로그인 실패 시각 기록 (DB 및 메모리 동기화)."""
    now = time.time()
    ident = (identifier or '').strip().lower()
    try:
        execute("INSERT INTO login_attempts (ip, identifier, failed_at) VALUES (?, ?, ?)", (ip, ident, now))
        # Cleanup old attempts > 24 hours
        execute("DELETE FROM login_attempts WHERE failed_at < ?", (now - 86400,))
    except Exception:
        pass
    key = f"{ip}:{ident}"
    with _login_failures_lock:
        attempts = [t for t in _login_failures.get(key, []) if now - t < 900]
        attempts.append(now)
        _login_failures[key] = attempts

def clear_login_failures(ip, identifier):
    """로그인 성공 시 해당 계정의 실패 기록만 초기화 (IP 레코드 삭제 방지하여 브루트포스 리셋 공격 차단)."""
    ident = (identifier or '').strip().lower()
    if ident:
        try:
            execute("DELETE FROM login_attempts WHERE identifier = ?", (ident,))
        except Exception:
            pass
    key = f"{ip}:{ident}"
    with _login_failures_lock:
        if key in _login_failures:
            del _login_failures[key]

def hash_session_token(token: str) -> str:
    """Computes SHA-256 hash of session token for secure database storage."""
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def create_session(name_or_user_id, org=None, email=None, user_id=None):
    """
    새 로그인 세션을 생성한다.
    세션 토큰을 SHA-256으로 해시하여 DB에 안전하게 저장한다 (Plaintext 세션 노출 방지).
    """
    u_id = user_id
    name = str(name_or_user_id or "")
    if isinstance(name_or_user_id, int):
        u_id = name_or_user_id
        u_row = get_user_by_id(u_id)
        if u_row:
            name = u_row.get("name") or name
            org = org or u_row.get("dept_id")
            email = email or u_row.get("email")
    elif not u_id:
        u_row = get_user_by_login(name, org)
        if not u_row and org:
            u_row = get_one("SELECT id, name, dept_id, email, role, is_admin FROM users WHERE LOWER(name) = ? AND LOWER(dept_id) = ? ORDER BY id ASC LIMIT 1", (name.lower(), str(org).lower()))
        if not u_row and email:
            u_row = get_one("SELECT id, name, dept_id, email, role, is_admin FROM users WHERE LOWER(email) = ? ORDER BY id ASC LIMIT 1", (email.lower(),))
        if not u_row:
            u_row = get_one("SELECT id, name, dept_id, email, role, is_admin FROM users WHERE LOWER(username) = ? ORDER BY id ASC LIMIT 1", (name.lower(),))
        if u_row:
            u_id = u_row["id"]
            name = u_row.get("name") or name
            org = org or u_row.get("dept_id")
            email = email or u_row.get("email")

    token = secrets.token_hex(24)
    token_hash = hash_session_token(token)
    ts = time.time()
    is_admin = is_admin_user(u_id or name)

    execute(
        """INSERT INTO sessions(token, user_id, user_name, user_dept_id, user_email, is_admin, created_at, last_active_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (token_hash, u_id, name, org or "", email or "", 1 if is_admin else 0, ts, ts)
    )
    return token

def get_session(token):
    """토큰으로 세션 정보를 반환한다 (SHA-256 해시 조회 및 슬라이딩 세션 갱신)."""
    if not token:
        return None

    token_hash = hash_session_token(token)
    row = get_one(
        """SELECT s.token, s.user_id, s.user_name, s.user_dept_id, s.user_email, s.created_at, s.last_active_at,
                  u.id AS u_id, u.name AS u_name, u.username AS u_username, u.dept_id AS u_dept_id,
                  u.email AS u_email, u.role AS u_role, u.is_admin AS u_is_admin,
                  u.disabled AS u_disabled, u.status AS u_status
           FROM sessions s
           LEFT JOIN users u ON (s.user_id IS NOT NULL AND s.user_id = u.id)
                             OR (s.user_id IS NULL AND LOWER(s.user_name) = LOWER(u.name) AND LOWER(s.user_dept_id) = LOWER(u.dept_id))
           WHERE s.token = ?""",
        (token_hash,)
    )
    if not row:
        return None

    created_at = row.get("created_at") or 0
    last_active = row.get("last_active_at") or created_at
    now = time.time()
    ttl = get_session_ttl_seconds()
    max_age = get_session_max_age_seconds()

    # 절대 만료기간(Absolute Expiration): 생성 시점(created_at)으로부터 max_age 경과 시 무조건 만료
    effective_created_at = created_at if created_at > 0 else last_active
    if effective_created_at > 0 and (now - effective_created_at > max_age):
        try:
            execute("DELETE FROM sessions WHERE token = ?", (token_hash,))
        except Exception as e:
            log_line("[auth] Error deleting absolute-expired session:", e)
        return None

    # 슬라이딩 유효기간(Sliding Expiration): 마지막 활동 후 ttl 경과 시 만료
    if now - last_active > ttl:
        try:
            execute("DELETE FROM sessions WHERE token = ?", (token_hash,))
        except Exception as e:
            log_line("[auth] Error deleting sliding-expired session:", e)
        return None

    # 활동 중인 세션은 5분마다 last_active_at 슬라이딩 갱신
    if now - last_active > 300:
        try:
            execute("UPDATE sessions SET last_active_at = ? WHERE token = ?", (now, token_hash))
        except Exception as e:
            log_line("[auth] Error updating session last_active_at:", e)

    u_id = row.get("u_id")
    if not u_id:
        return None
    if row.get("u_disabled") or row.get("u_status") != "active":
        return None

    user_role = row.get("u_role") or "member"
    is_admin = bool(user_role == "admin" or row.get("u_is_admin") == 1)
    if is_admin:
        user_role = "admin"

    return {
        "id": u_id,
        "user_id": u_id,
        "name": row.get("u_name") or row["user_name"],
        "username": row.get("u_username") or row["user_name"],
        "org": row.get("u_dept_id") or row["user_dept_id"],
        "dept_id": row.get("u_dept_id") or row["user_dept_id"],
        "email": row.get("u_email") or row["user_email"],
        "isAdmin": is_admin,
        "is_admin": is_admin,
        "role": user_role,
        "disabled": row.get("u_disabled") or 0,
        "status": row.get("u_status") or "active",
        "ts": created_at,
        "last_active": last_active
    }

def delete_session(token):
    """단일 세션 만료 (로그아웃)."""
    if token:
        token_hash = hash_session_token(token)
        try:
            execute("DELETE FROM sessions WHERE token = ?", (token_hash,))
        except Exception as e:
            log_line("[auth] Error deleting session:", e)

def rotate_session(old_token):
    """권한 변경 또는 주기적 세션 토큰 교체 (Session Rotation)."""
    sess = get_session(old_token)
    if not sess:
        return None
    delete_session(old_token)
    return create_session(
        name_or_user_id=sess["name"],
        org=sess["org"],
        email=sess["email"],
        user_id=sess["id"]
    )

def delete_all_user_sessions(user_id_or_name):
    """해당 사용자의 모든 기기 세션 강제 만료 (Logout from all devices)."""
    if user_id_or_name is not None and user_id_or_name != "":
        try:
            if isinstance(user_id_or_name, int) or (isinstance(user_id_or_name, str) and str(user_id_or_name).isdigit()):
                execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id_or_name),))
            else:
                execute("DELETE FROM sessions WHERE user_name = ? OR user_id IN (SELECT id FROM users WHERE username = ?)", (str(user_id_or_name), str(user_id_or_name)))
        except Exception as e:
            log_line("[auth] Error deleting all user sessions:", e)

def cleanup_expired_sessions():
    """
    주기적으로 만료된 세션을 정리한다.
    슬라이딩 만료(마지막 활동 + TTL) 및 절대 만료(생성 시점 + MAX_AGE)를 모두 적용한다.
    """
    now = time.time()
    sliding_cutoff = now - get_session_ttl_seconds()
    max_age_cutoff = now - get_session_max_age_seconds()
    try:
        execute(
            """DELETE FROM sessions
               WHERE COALESCE(NULLIF(last_active_at, 0), created_at) < ?
                  OR (created_at > 0 AND created_at < ?)""",
            (sliding_cutoff, max_age_cutoff)
        )
    except Exception as e:
        log_line("[auth] Error cleaning up expired sessions:", e)


