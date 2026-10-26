"""
seed_demo_data.py — B2B Enterprise Sample Data Generator for ARGOS WORKS (Korean Native)

Clears existing test records and populates realistic, high-fidelity Korean
enterprise sample data:
- 5 Standard Korean Corporate Departments (경영지원·기획실, 소프트웨어·AI개발팀, B2B사업·고객지원팀, 인사총무·운영관리팀, 품질관리·감사준법팀)
- 8 Standard Korean Corporate Users with realistic executive & specialist titles
  (Password for all demo accounts: Argos@2026!)
- Realistic Records across Kanban stages (대기, 진행, 검토, 완료)
- Korean Collaboration Comments on tasks
- Korean PIM Products & Categories (IoT Sensors, Gateways, Edge AI, Software Licenses)
- Korean Schedules & Lounge Announcements
- Clean Audit Logs in Korean
- Valid Enterprise License (50 Seats)
"""

import os
import sys
import sqlite3
import hashlib
from datetime import datetime, timedelta

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
sys.path.insert(0, SERVER_DIR)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "argos.db")
PBKDF2_ROUNDS = 600000


def hash_pwd(password: str):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return salt.hex(), digest.hex()


def run_seed():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF;")
    cur = conn.cursor()

    print("[1/8] Cleaning up existing transactional and test records...")
    tables_to_clear = [
        "sessions",
        "chat_messages",
        "chat_sessions",
        "record_comments",
        "record_attachments",
        "record_jira",
        "records",
        "schedule_participants",
        "schedule_events",
        "product_attachments",
        "products",
        "product_categories",
        "lounge_messages",
        "notifications",
        "audit_logs",
        "ai_usage",
        "login_attempts",
        "users",
        "card_sequences",
        "departments",
        "license_info"
    ]
    for tbl in tables_to_clear:
        try:
            cur.execute(f"DELETE FROM {tbl};")
        except sqlite3.OperationalError:
            pass

    print("[2/8] Seeding Standard Korean Enterprise Departments...")
    departments = [
        ("mgmt", "경영지원·기획실", 1, "MGMT", "MGMT", '["경영전략","예산승인","주간보고","대외협력"]'),
        ("dev", "소프트웨어·AI개발팀", 2, "DEV", "ARGOS", '["인프라","기능개발","보안강화","성능최적화","API연동"]'),
        ("sales", "B2B사업·고객지원팀", 3, "SALES", "SALES", '["계약체결","고객사미팅","입찰제안","기술지원"]'),
        ("hr", "인사총무·운영관리팀", 4, "HR", "HR", '["채용","직무교육","사내복지","인프라지원"]'),
        ("hq", "품질관리·감사준법팀", 5, "HQ", "HQ", '["내부감사","보안점검","SLA검증","인증심사"]')
    ]
    cur.executemany(
        """INSERT INTO departments (id, name, color_index, local_prefix, jira_key, custom_categories)
           VALUES (?, ?, ?, ?, ?, ?)""",
        departments
    )

    for d in departments:
        cur.execute("INSERT INTO card_sequences (dept_id, last_seq) VALUES (?, 100)", (d[0],))

    print("[3/8] Seeding Korean Enterprise Users (Password: Argos@2026!)...")
    salt_hex, hash_hex = hash_pwd("Argos@2026!")
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    users_data = [
        # id, username, name, dept_id, email, is_admin, role, status
        (1, "admin", "김민수", "mgmt", "minsoo.kim@argosworks.kr", 1, "admin", "active"),
        (2, "lee.dh", "이도현", "dev", "dohyun.lee@argosworks.kr", 1, "manager", "active"),
        (3, "park.sj", "박서준", "dev", "seojun.park@argosworks.kr", 0, "member", "active"),
        (4, "choi.yj", "최유진", "dev", "yujin.choi@argosworks.kr", 0, "member", "active"),
        (5, "jung.hn", "정하나", "sales", "hana.jung@argosworks.kr", 0, "manager", "active"),
        (6, "kang.dw", "강동원", "sales", "dongwon.kang@argosworks.kr", 0, "member", "active"),
        (7, "han.sy", "한소영", "hr", "soyoung.han@argosworks.kr", 0, "manager", "active"),
        (8, "yoon.jh", "윤재호", "hq", "jaeho.yoon@argosworks.kr", 0, "viewer", "active"),
    ]

    for u in users_data:
        cur.execute(
            """INSERT INTO users (id, username, name, dept_id, email, avatar_url, salt, password_hash,
                                  hash_algo, iterations, is_admin, role, disabled, status, created_at)
               VALUES (?, ?, ?, ?, ?, '', ?, ?, 'pbkdf2_sha256', ?, ?, ?, 0, ?, ?)""",
            (u[0], u[1], u[2], u[3], u[4], salt_hex, hash_hex, PBKDF2_ROUNDS, u[5], u[6], u[7], now_iso)
        )

    print("[4/8] Seeding Realistic Korean B2B Records & Kanban Tasks...")
    base_time = int(datetime.now().timestamp() * 1000)
    today = datetime.now()
    d_m7 = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    d_m3 = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    d_today = today.strftime("%Y-%m-%d")
    d_p3 = (today + timedelta(days=3)).strftime("%Y-%m-%d")
    d_p7 = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    d_p14 = (today + timedelta(days=14)).strftime("%Y-%m-%d")

    records_data = [
        # (id, dept_id, category, title, project, assignee_id, assignee_name, assignee_email, start_date, due_date, status, card_code, priority, memo, jira_key)
        (base_time + 1, "dev", "인프라", "온프레미스 격리망 전용 서버 클러스터 구축 및 네트워크 이중화",
         "2026 인프라 현대화", 2, "이도현", "dohyun.lee@argosworks.kr", d_m7, d_m3, "완료", "DEV-101", "긴급",
         "사내 폐쇄망 환경에서 외부 인터넷 연결 없이 독립 구동되는 서버 랙 구성 완료 및 내부 10Gbps 백본 연동 검증 완료.", "ARGOS-101"),

        (base_time + 2, "dev", "보안강화", "SQLite 및 PostgreSQL 저장소 AES-256 파일 암호화 모듈 적용",
         "2026 인프라 현대화", 3, "박서준", "seojun.park@argosworks.kr", d_m3, d_p3, "진행", "DEV-102", "긴급",
         "서버 재부팅 시 마스터 키 기반 하드웨어 HSM 검증 모듈 연동 및 감사 로그 위변조 방지 무결성 서명 체계 적용.", "ARGOS-102"),

        (base_time + 3, "dev", "기능개발", "로컬 사내 AI LLM 엔진(Ollama/vLLM) 문서 질의 RAG 모듈 최적화",
         "차세대 AI 어시스턴트", 4, "최유진", "yujin.choi@argosworks.kr", d_m3, d_p7, "진행", "DEV-103", "높음",
         "외부 클라우드 유출 없는 사내 GPU 서버 전용 파라미터 경량화(7B 모델) 연동. 초당 45 토큰 처리 확인 및 응답 지연 최소화.", "ARGOS-103"),

        (base_time + 4, "dev", "API연동", "아틀라시안 Jira Data Center 온프레미스 2-way 웹훅 실시간 동기화",
         "아르고스 커넥터", 3, "박서준", "seojun.park@argosworks.kr", d_today, d_p7, "진행", "DEV-104", "높음",
         "사내 Jira 이슈 상태 변경 시 아르고스 칸반 카드로 0.5초 이내 양방향 미러링 검증 완료. 충돌 방지 버전 제어 로직 탑재.", "ARGOS-104"),

        (base_time + 5, "sales", "고객사미팅", "(주)한국통신기술 차세대 엔터프라이즈 운영 플랫폼 PoC 결과 보고",
         "2026 핵심 수주 프로젝트", 5, "정하나", "hana.jung@argosworks.kr", d_m7, d_p3, "진행", "SALES-201", "긴급",
         "Local-First 폐쇄망 아키텍처 및 RBAC 다단계 권한 분리 모델 시연 완료. 고객사 보안심의 A등급 획득.", "SALES-201"),

        (base_time + 6, "sales", "입찰제안", "제조 대기업 대상 50 Seats 온프레미스 영구 라이선스 공급 제안서 작성",
         "2026 핵심 수주 프로젝트", 6, "강동원", "dongwon.kang@argosworks.kr", d_today, d_p7, "검토", "SALES-202", "보통",
         "초기 구축비용 및 24/7 기술지원 SLA를 포함한 TCO 3개년 비용 절감 분석표 작성 완료. 경영진 최종 검토 요청.", "SALES-202"),

        (base_time + 7, "hr", "채용", "2026년 하반기 핵심 임베디드 및 백엔드 개발자 2명 온보딩 절차 완료",
         "인재영입 및 조직관리", 7, "한소영", "soyoung.han@argosworks.kr", d_m7, d_m3, "완료", "HR-301", "보통",
         "사내 정보보호 서약서 징구, 개발 워크스테이션 지급 및 아르고스 워크스 전용 계정 권한 발급 완료.", "HR-301"),

        (base_time + 8, "hr", "직무교육", "전사 임직원 정보보호 가이드라인 및 사내 AI 비서 활용 세미나 개최",
         "인재영입 및 조직관리", 7, "한소영", "soyoung.han@argosworks.kr", d_today, d_p14, "대기", "HR-302", "보통",
         "외부 상용 AI 툴 보안사고 방지 및 사내 구축형 RAG 어시스턴트 활용법 전사 교육 준비.", "HR-302"),

        (base_time + 9, "mgmt", "경영전략", "2027년도 온프레미스 AI 전용 컴퓨팅 인프라 확장 예산안 승인",
         "중장기 사업계획", 1, "김민수", "minsoo.kim@argosworks.kr", d_m3, d_p3, "검토", "MGMT-401", "높음",
         "고성능 GPU 연산 서버 2노드 추가 도입에 대한 경제성 및 투자 대비 효과(ROI) 최종 심의 및 결재.", "MGMT-401"),

        (base_time + 10, "hq", "내부감사", "전사 4단계 권한 매트릭스(RBAC) 및 보안 감사 로그 무결성 전수 점검",
         "상시 내부통제", 8, "윤재호", "jaeho.yoon@argosworks.kr", d_m3, d_p7, "진행", "HQ-501", "높음",
         "최근 10,000건의 사용자 접속 및 데이터 변경 감사 로그 전수 검증 결과 위변조 없음 확인.", "HQ-501")
    ]

    for r in records_data:
        cur.execute(
            """INSERT INTO records (id, dept_id, category, title, project, assignee_id, assignee_name,
                                    assignee_email, start_date, due_date, work_date, summary, tags, memo,
                                    status, priority, card_code, participants, parent_key, is_scheduled,
                                    version, is_private, updated_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '["엔터프라이즈","온프레미스","B2B"]', ?, ?, ?, ?, '', '', 1, 1, 0, ?, ?)""",
            (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], f"{r[8]} ~ {r[9]}", r[3],
             r[13], r[10], r[12], r[11], now_iso, now_iso)
        )
        cur.execute(
            """INSERT INTO record_jira (record_id, jira_key, jira_status, jira_url)
               VALUES (?, ?, ?, ?)""",
            (r[0], r[14], "IN_PROGRESS" if r[10] == "진행" else ("DONE" if r[10] == "완료" else "TO_DO"),
             f"https://jira.internal.argosworks.kr/browse/{r[14]}")
        )

    print("[5/8] Seeding Professional Korean Task Comments...")
    comments_data = [
        (base_time + 1, "이도현", "서버 랙 구축 및 방화벽 DMZ 분리 설정 완료되었습니다. 로컬 네트워크 지연시간 0.3ms 이하로 매우 안정적입니다.", now_iso),
        (base_time + 2, "박서준", "데이터베이스 마스터 키는 /etc/argos/security/master.key 권한 600으로 안전하게 보관되었습니다.", now_iso),
        (base_time + 3, "최유진", "사내 RAG 벡터 인덱싱 완료 후 기술 매뉴얼 질의 정확도 96% 달성했습니다. 외부 통신 전혀 발생하지 않습니다.", now_iso),
        (base_time + 4, "박서준", "Jira Data Center 웹훅 수신 엔드포인트에 HMAC-SHA256 서명 검증 로직이 추가되었습니다.", now_iso),
        (base_time + 5, "정하나", "고객사 CISO 인터뷰에서 클라우드 SaaS 대비 데이터 유출 위험이 제로라는 점에 대해 최고점을 받았습니다.", now_iso),
        (base_time + 9, "김민수", "예산안 검토 완료되었습니다. 재무기획팀과 협의하여 다음 주 집행 일정 확정하겠습니다.", now_iso),
        (base_time + 10, "윤재호", "감사 로그 전수 점검 결과, 인가되지 않은 권한 상승 시도 0건이며 무결성이 완벽히 유지되고 있습니다.", now_iso)
    ]
    for c in comments_data:
        cur.execute(
            """INSERT INTO record_comments (record_id, author_name, body, created_at)
               VALUES (?, ?, ?, ?)""",
            c
        )

    print("[6/8] Seeding Korean Enterprise PIM Products & Categories...")
    categories = [
        ("cat-iot", "산업용 IoT 센서 및 계측 시스템", '[{"name":"통신 프로토콜","type":"select","options":["RS485","Modbus","Ethernet"]},{"name":"방수방진 등급","type":"text"}]'),
        ("cat-gw", "산업용 엣지 게이트웨이 (Edge Gateway)", '[{"name":"LAN 포트 수","type":"number"},{"name":"전원 공급","type":"text"}]'),
        ("cat-ai", "온프레미스 엣지 AI 비전 분석 모듈", '[{"name":"연산 능력","type":"text"},{"name":"NPU 성능","type":"text"}]'),
        ("cat-lic", "아르고스 워크스 구축형 엔터프라이즈 라이선스", '[{"name":"사용자 수","type":"number"},{"name":"유지보수 기간","type":"text"}]')
    ]
    cur.executemany("INSERT INTO product_categories (id, name, spec_template, created_at) VALUES (?, ?, ?, ?)",
                    [(c[0], c[1], c[2], now_iso) for c in categories])

    products_data = [
        ("ARGOS-IOT-S300", "ARGOS-IOT-S300", "아르고스 S300 산업용 진동·온도 복합 센서", "S-시리즈 산업용 센서",
         "판매 중", "산업용 IoT 센서 및 계측 시스템", "IP68 방수방진 지원 고정밀 진동 및 온도 모니터링 복합 계측 센서",
         "Modbus-RTU / RS485 지원, 측정 온도 범위 -40℃ ~ 125℃",
         '{"통신 프로토콜":"Modbus-RTU","방수방진 등급":"IP68","측정 범위":"-40℃ ~ 125℃"}',
         850000, "KRW", "internal"),

        ("ARGOS-GW-EDGE2", "ARGOS-GW-EDGE2", "아르고스 Edge-V2 4포트 광절연 산업용 게이트웨이", "Edge 게이트웨이 제품군",
         "판매 중", "산업용 엣지 게이트웨이 (Edge Gateway)", "이중화 LAN 및 하드웨어 광절연 설계를 적용한 산업용 통신 게이트웨이",
         "이중 전원 12-24V DC 지원, 알루미늄 일체형 무팬 방열 구조",
         '{"LAN 포트 수":4,"전원 공급":"DC 12-24V 이중화","케이스":"알루미늄 압출 방열"}',
         1680000, "KRW", "internal"),

        ("ARGOS-AI-BOX1", "ARGOS-AI-BOX1", "아르고스 Vision-Box 엣지 AI 추론 연산 장치", "Vision AI 장치군",
         "판매 중", "온프레미스 엣지 AI 비전 분석 모듈", "실시간 비전 분석 및 센서 스트림 데이터 로컬 추론을 위한 독립형 엣지 컴퓨터",
         "32 TOPS NPU 탑재, 16GB LPDDR5 ECC 메모리, Argos Linux Core OS 탑재",
         '{"연산 능력":"32 TOPS","메모리":"16GB ECC","운영체제":"Argos Linux Core"}',
         3250000, "KRW", "internal"),

        ("ARGOS-LIC-ENT50", "ARGOS-LIC-ENT50", "ARGOS WORKS Enterprise 구축형 영구 라이선스 (50인)", "소프트웨어 솔루션",
         "판매 중", "아르고스 워크스 구축형 엔터프라이즈 라이선스", "사내 폐쇄망 구축형 올인원 업무 포털 영구 라이선스 (50인 사용자 기본 제공)",
         "칸반 보드, PIM 제품 관리, 사내 AI RAG 비서, Jira 2-way 연동 및 보안 감사 로그 포함",
         '{"사용자 수":50,"유지보수 기간":"1년 무상 (이후 연간 유지보수 계약)","제공 형태":"구축형 패키지"}',
         15000000, "KRW", "internal")
    ]
    cur.executemany(
        """INSERT INTO products (id, model, display_name, family, lifecycle, category, summary, memo, specs, price, currency, revision, created_at, updated_at, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
        [(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9], p[10], now_iso, now_iso, p[11]) for p in products_data]
    )

    print("[7/8] Seeding Korean Corporate Schedules & Lounge Announcements...")
    schedules = [
        (base_time + 101, 1, "김민수", "mgmt", "minsoo.kim@argosworks.kr", "meeting",
         "주간 정례 경영전략 및 부서장 회의",
         f"{d_today} 09:00", f"{d_today} 10:30", "전사 핵심 프로젝트 진척률 점검, 분기 예산 집행 현황 및 전략 과제 승인."),
        (base_time + 102, 2, "이도현", "dev", "dohyun.lee@argosworks.kr", "sprint",
         "Jira Data Center 연동 및 로컬 AI 엔진 스프린트 리뷰",
         f"{d_p3} 14:00", f"{d_p3} 15:30", "Jira 온프레미스 실시간 웹훅 연동 결과 시연 및 사내 RAG 문서 질의 응답 속도 검증."),
        (base_time + 103, 5, "정하나", "sales", "hana.jung@argosworks.kr", "client",
         "엔터프라이즈 B2B Local-First 솔루션 데모 시연회",
         f"{d_p7} 10:00", f"{d_p7} 11:30", "대기업 고객사 대상 폐쇄망 독립 운영 구조 및 RBAC 4단계 권한 제어 모델 현장 시연.")
    ]
    cur.executemany(
        """INSERT INTO schedule_events (id, owner_id, owner_name, owner_dept_id, owner_email, type, title, start_date, end_date, memo, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], now_iso) for s in schedules]
    )
    for s in schedules:
        cur.execute(
            """INSERT INTO schedule_participants (event_id, user_name, user_dept_id, user_email, is_owner)
               VALUES (?, ?, ?, ?, 1)""",
            (s[0], s[2], s[3], s[4])
        )

    lounge_msgs = [
        (base_time + 201, "general", "김민수", "mgmt", "전체 임직원", "all",
         "2026년도 하반기 ARGOS WORKS 온프레미스 플랫폼이 정식 배포되었습니다. 임직원 여러분 모두 안전하고 생산적인 한 주 되시길 바랍니다.", now_iso),
        (base_time + 202, "general", "이도현", "dev", "전체 임직원", "all",
         "보안 공지: 사내 모든 연구 데이터와 작업 카드는 온프레미스 격리망 내에 안전하게 암호화되어 보관됩니다. 외부 유출 위험 없이 안심하고 활용하세요.", now_iso),
        (base_time + 203, "general", "정하나", "sales", "전체 임직원", "all",
         "영업 브리핑: 금일 대기업 고객사 미팅에서 Jira 2-way 연동과 로컬 비서 기능에 대해 최고 수준의 호평을 받았습니다.", now_iso)
    ]
    cur.executemany(
        """INSERT INTO lounge_messages (id, conversation_key, from_name, from_dept_id, to_name, to_dept_id, text, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        lounge_msgs
    )

    print("[8/8] Seeding Enterprise Trial License & Initial Audit Logs...")
    # Trial license is a signed artifact kept in licenses/trial-50.lic; never
    # hardcode an unsigned license string (it would be rejected at runtime).
    trial_license_key = ""
    trial_license_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "licenses", "trial-50.lic")
    try:
        with open(trial_license_path, "r", encoding="utf-8") as f:
            trial_license_key = f.read().strip()
    except Exception as e:
        print(f"  [WARN] trial license not found ({trial_license_path}): {e}")

    cur.execute(
        """INSERT INTO license_info (id, customer_name, license_key, max_seats, expiry_date, modules_json, is_active, updated_at)
           VALUES (1, 'Argos Enterprise Trial', ?, 50, '2027-12-31',
                   '[\"canvas\",\"pim\",\"jira\",\"rag\",\"schedule\",\"audit\"]', 1, ?)""",
        (trial_license_key, now_iso)
    )

    audit_logs = [
        (now_iso, "system", "SYSTEM_BOOTSTRAP", "database", "1", '{"action":"clean_seed","architecture":"korean_local_first_b2b"}'),
        (now_iso, "admin", "LICENSE_ACTIVATED", "license", "1", '{"seats":50,"type":"enterprise_local","customer":"(주)아르고스 솔루션즈"}'),
        (now_iso, "admin", "ORGANIZATION_SETUP", "departments", "5", '{"departments":["mgmt","dev","sales","hr","hq"]}'),
        (now_iso, "admin", "USER_MANAGEMENT", "users", "8", '{"status":"active","roles":["admin","manager","member","viewer"]}')
    ]
    cur.executemany(
        """INSERT INTO audit_logs (timestamp, username, action, target_type, target_id, details_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        audit_logs
    )

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.commit()
    conn.close()
    print(">>> Korean enterprise sample data seed completed successfully!")


if __name__ == "__main__":
    run_seed()
