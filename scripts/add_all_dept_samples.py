"""
add_all_dept_samples.py — Adds high-fidelity B2B enterprise sample data across all departments:
- mgmt: 경영기획팀 (Management)
- dev: 연구개발팀 (R&D)
- sales: B2B사업·고객지원팀
- hr: 인사총무·운영관리팀
- hq: 품질관리·감사준법팀
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "argos.db")

def seed():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Update custom_categories and prefixes for departments
    dept_configs = [
        ("mgmt", "경영기획팀 (Management)", 1, "MGMT", "MGMT", "경영전략, 예산승인, 주간보고, 대외협력"),
        ("dev", "연구개발팀 (R&D)", 2, "DEV", "ARGOS", "인프라, 기능개발, 보안강화, 성능최적화, API연동"),
        ("sales", "B2B사업·고객지원팀", 3, "SALES", "SALES", "계약체결, 고객사미팅, 입찰제안, 기술지원"),
        ("hr", "인사총무·운영관리팀", 4, "HR", "HR", "채용, 직무교육, 사내복지, 인프라지원"),
        ("hq", "품질관리·감사준법팀", 5, "HQ", "HQ", "내부감사, 보안점검, SLA검증, 인증심사")
    ]
    for d in dept_configs:
        cur.execute("""
            INSERT INTO departments (id, name, color_index, local_prefix, jira_key, custom_categories)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                color_index = excluded.color_index,
                local_prefix = excluded.local_prefix,
                jira_key = excluded.jira_key,
                custom_categories = excluded.custom_categories
        """, d)

    # 2. Clear old demo records to ensure clean state across all departments
    cur.execute("DELETE FROM record_comments;")
    cur.execute("DELETE FROM record_jira;")
    cur.execute("DELETE FROM records;")

    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    today = datetime.now()
    d_m7 = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    d_m5 = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    d_m3 = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    d_m1 = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    d_today = today.strftime("%Y-%m-%d")
    d_p2 = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    d_p5 = (today + timedelta(days=5)).strftime("%Y-%m-%d")
    d_p7 = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    d_p14 = (today + timedelta(days=14)).strftime("%Y-%m-%d")

    base_id = int(datetime.now().timestamp() * 1000)

    # List of realistic records for all 5 departments
    records_to_insert = [
        # ==================== MGMT (경영기획팀) ====================
        {
            "id": base_id + 1, "dept_id": "mgmt", "category": "경영전략",
            "title": "2027년도 온프레미스 AI 전용 컴퓨팅 인프라 확장 예산안 승인",
            "project": "중장기 사업계획", "assignee_id": 1, "assignee_name": "김민수",
            "assignee_email": "minsoo.kim@argosworks.kr", "start_date": d_m5, "due_date": d_p5,
            "status": "검토", "card_code": "MGMT-101", "priority": "높음",
            "memo": "고성능 GPU 연산 서버 2노드 추가 도입에 대한 경제성 및 투자 대비 효과(ROI) 최종 심의 및 결재.",
            "jira_key": "MGMT-101", "jira_status": "IN_REVIEW"
        },
        {
            "id": base_id + 2, "dept_id": "mgmt", "category": "예산승인",
            "title": "Q4 사내 하드웨어 서버 클러스터 및 네트워크 장비 도입 예산 결재",
            "project": "2026 예산운용", "assignee_id": 1, "assignee_name": "김민수",
            "assignee_email": "minsoo.kim@argosworks.kr", "start_date": d_m7, "due_date": d_m1,
            "status": "완료", "card_code": "MGMT-102", "priority": "보통",
            "memo": "연구개발팀 고성능 워크스테이션 및 10Gbps 백본 스위치 교체 건 최종 승인 완료.",
            "jira_key": "MGMT-102", "jira_status": "DONE"
        },
        {
            "id": base_id + 3, "dept_id": "mgmt", "category": "대외협력",
            "title": "국내 주요 방산 및 공공기관 대상 폐쇄망 솔루션 전략적 제휴 협약 체결",
            "project": "전략적 제휴", "assignee_id": 1, "assignee_name": "김민수",
            "assignee_email": "minsoo.kim@argosworks.kr", "start_date": d_m3, "due_date": d_p7,
            "status": "진행", "card_code": "MGMT-103", "priority": "긴급",
            "memo": "국가보안기술연구소 기준 충족 및 전략적 공급 파트너십 MOU 초안 법률 검토.",
            "jira_key": "MGMT-103", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 4, "dept_id": "mgmt", "category": "주간보고",
            "title": "전사 핵심 KPI 및 분기별 프로젝트 마일스톤 달성도 총괄 점검",
            "project": "경영총괄", "assignee_id": 1, "assignee_name": "김민수",
            "assignee_email": "minsoo.kim@argosworks.kr", "start_date": d_today, "due_date": d_p14,
            "status": "대기", "card_code": "MGMT-104", "priority": "보통",
            "memo": "5개 부서 핵심 지표 달성도 집계 및 차기 분기 사업계획 수립 회의 준비.",
            "jira_key": "MGMT-104", "jira_status": "TO_DO"
        },

        # ==================== DEV (연구개발팀) ====================
        {
            "id": base_id + 11, "dept_id": "dev", "category": "인프라",
            "title": "온프레미스 격리망 전용 서버 클러스터 구축 및 네트워크 이중화",
            "project": "2026 인프라 현대화", "assignee_id": 2, "assignee_name": "이도현",
            "assignee_email": "dohyun.lee@argosworks.kr", "start_date": d_m7, "due_date": d_m1,
            "status": "완료", "card_code": "DEV-101", "priority": "긴급",
            "memo": "사내 폐쇄망 환경에서 외부 인터넷 연결 없이 독립 구동되는 서버 랙 구성 완료 및 내부 10Gbps 백본 연동 검증 완료.",
            "jira_key": "ARGOS-101", "jira_status": "DONE"
        },
        {
            "id": base_id + 12, "dept_id": "dev", "category": "성능최적화",
            "title": "마이크로서비스 IPC 통신 지연시간 0.5ms 이하 단축 최적화",
            "project": "차세대 엔진 고도화", "assignee_id": 2, "assignee_name": "이도현",
            "assignee_email": "dohyun.lee@argosworks.kr", "start_date": d_m3, "due_date": d_p5,
            "status": "진행", "card_code": "DEV-102", "priority": "높음",
            "memo": "Unix Domain Socket 기반 고속 데이터 파이프라인 적용 및 메모리 풀링 튜닝.",
            "jira_key": "ARGOS-102", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 13, "dept_id": "dev", "category": "보안강화",
            "title": "SQLite 및 PostgreSQL 저장소 AES-256 파일 암호화 모듈 적용",
            "project": "2026 인프라 현대화", "assignee_id": 3, "assignee_name": "박서준",
            "assignee_email": "seojun.park@argosworks.kr", "start_date": d_m5, "due_date": d_p2,
            "status": "진행", "card_code": "DEV-103", "priority": "긴급",
            "memo": "서버 재부팅 시 마스터 키 기반 하드웨어 HSM 검증 모듈 연동 및 감사 로그 위변조 방지 무결성 서명 체계 적용.",
            "jira_key": "ARGOS-103", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 14, "dept_id": "dev", "category": "API연동",
            "title": "아틀라시안 Jira Data Center 온프레미스 2-way 웹훅 실시간 동기화",
            "project": "아르고스 커넥터", "assignee_id": 3, "assignee_name": "박서준",
            "assignee_email": "seojun.park@argosworks.kr", "start_date": d_today, "due_date": d_p7,
            "status": "진행", "card_code": "DEV-104", "priority": "높음",
            "memo": "사내 Jira 이슈 상태 변경 시 아르고스 칸반 카드로 0.5초 이내 양방향 미러링 검증 완료.",
            "jira_key": "ARGOS-104", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 15, "dept_id": "dev", "category": "기능개발",
            "title": "로컬 사내 AI LLM 엔진(Ollama/vLLM) 문서 질의 RAG 모듈 최적화",
            "project": "차세대 AI 어시스턴트", "assignee_id": 4, "assignee_name": "최유진",
            "assignee_email": "yujin.choi@argosworks.kr", "start_date": d_m3, "due_date": d_p7,
            "status": "진행", "card_code": "DEV-105", "priority": "높음",
            "memo": "외부 클라우드 유출 없는 사내 GPU 서버 전용 파라미터 경량화(7B 모델) 연동. 초당 45 토큰 처리 확인.",
            "jira_key": "ARGOS-105", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 16, "dept_id": "dev", "category": "기능개발",
            "title": "사내 문서 다국어 자동 번역 및 요약 로컬 파이프라인 구축",
            "project": "차세대 AI 어시스턴트", "assignee_id": 4, "assignee_name": "최유진",
            "assignee_email": "yujin.choi@argosworks.kr", "start_date": d_m5, "due_date": d_p5,
            "status": "검토", "card_code": "DEV-106", "priority": "보통",
            "memo": "영어/한국어/베트남어/일본어 기술 문서 오프라인 일괄 번역 캐싱 모듈 개발.",
            "jira_key": "ARGOS-106", "jira_status": "IN_REVIEW"
        },
        {
            "id": base_id + 17, "dept_id": "dev", "category": "기능개발",
            "title": "칸반 대시보드 실시간 반응형 차트 및 드래그 앤 드롭 UX 고도화",
            "project": "대시보드 2.0", "assignee_id": 997513, "assignee_name": "홍길동",
            "assignee_email": "hong@test.com", "start_date": d_m3, "due_date": d_p2,
            "status": "진행", "card_code": "DEV-107", "priority": "보통",
            "memo": "부서별 담당자 통계 카드 높이 자동 조절 및 터치 디바이스 최적화.",
            "jira_key": "ARGOS-107", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 18, "dept_id": "dev", "category": "성능최적화",
            "title": "대용량 작업 카드 렌더링 가상화(Virtual Scroll) 적용",
            "project": "대시보드 2.0", "assignee_id": 997513, "assignee_name": "홍길동",
            "assignee_email": "hong@test.com", "start_date": d_m7, "due_date": d_m1,
            "status": "완료", "card_code": "DEV-108", "priority": "보통",
            "memo": "1,000건 이상의 카드 목록 스크롤 시 60fps 렌더링 성능 확보.",
            "jira_key": "ARGOS-108", "jira_status": "DONE"
        },
        {
            "id": base_id + 19, "dept_id": "dev", "category": "기능개발",
            "title": "REST API 엔드포인트 자동화 검증 테스트 스위트 작성",
            "project": "QA 자동화", "assignee_id": 9004, "assignee_name": "MemDev",
            "assignee_email": "memdev@test.com", "start_date": d_m7, "due_date": d_m3,
            "status": "완료", "card_code": "DEV-109", "priority": "보통",
            "memo": "Pytest 기반 68개 유닛 및 통합 테스트 케이스 100% 통과 완료.",
            "jira_key": "ARGOS-109", "jira_status": "DONE"
        },
        {
            "id": base_id + 20, "dept_id": "dev", "category": "보안강화",
            "title": "사내 API 토큰 순환 주기 단축 및 세션 만료 검증 로직 구현",
            "project": "QA 자동화", "assignee_id": 9004, "assignee_name": "MemDev",
            "assignee_email": "memdev@test.com", "start_date": d_today, "due_date": d_p7,
            "status": "대기", "card_code": "DEV-110", "priority": "보통",
            "memo": "JWT 세션 만료 시간 8시간으로 단축 및 자동 갱신 인터셉터 추가.",
            "jira_key": "ARGOS-110", "jira_status": "TO_DO"
        },
        {
            "id": base_id + 21, "dept_id": "dev", "category": "인프라",
            "title": "사내 개발망 CI/CD 파이프라인 무중단 배포 및 롤백 체계 수립",
            "project": "2026 인프라 현대화", "assignee_id": 9002, "assignee_name": "MgrDev",
            "assignee_email": "mgrdev@test.com", "start_date": d_m5, "due_date": d_p2,
            "status": "검토", "card_code": "DEV-111", "priority": "높음",
            "memo": "Blue-Green 배포 스크립트 작성 및 헬스체크 실패 시 10초 내 자동 롤백 검증.",
            "jira_key": "ARGOS-111", "jira_status": "IN_REVIEW"
        },
        {
            "id": base_id + 22, "dept_id": "dev", "category": "보안강화",
            "title": "공공망 전용 국가정보원 암호모듈 검증(KCMVP) 기술 요건 분석",
            "project": "공공/국방 컴플라이언스", "assignee_id": 9001, "assignee_name": "AdminGov",
            "assignee_email": "admingov@test.com", "start_date": d_m3, "due_date": d_p7,
            "status": "진행", "card_code": "DEV-112", "priority": "긴급",
            "memo": "난수 발생기 적합성 및 SHA-256 해시 무결성 검증 명세서 작성.",
            "jira_key": "ARGOS-112", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 23, "dept_id": "dev", "category": "기능개발",
            "title": "개발 문서 및 API Swagger 사내 오프라인 뷰어 패키징",
            "project": "개발자 생산성", "assignee_id": 9005, "assignee_name": "ViewDev",
            "assignee_email": "viewdev@test.com", "start_date": d_m7, "due_date": d_m1,
            "status": "완료", "card_code": "DEV-113", "priority": "낮음",
            "memo": "오프라인 환경에서도 열람 가능한 단일 HTML 번들 문서 생성 완료.",
            "jira_key": "ARGOS-113", "jira_status": "DONE"
        },

        # ==================== SALES (B2B사업·고객지원팀) ====================
        {
            "id": base_id + 31, "dept_id": "sales", "category": "고객사미팅",
            "title": "(주)한국통신기술 차세대 엔터프라이즈 운영 플랫폼 PoC 결과 보고",
            "project": "2026 핵심 수주 프로젝트", "assignee_id": 5, "assignee_name": "정하나",
            "assignee_email": "hana.jung@argosworks.kr", "start_date": d_m7, "due_date": d_p2,
            "status": "진행", "card_code": "SALES-201", "priority": "긴급",
            "memo": "Local-First 폐쇄망 아키텍처 및 RBAC 다단계 권한 분리 모델 시연 완료. 고객사 보안심의 A등급 획득.",
            "jira_key": "SALES-201", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 32, "dept_id": "sales", "category": "계약체결",
            "title": "제조 대기업 엔터프라이즈 영구 라이선스 50 Seats 최종 계약 체결",
            "project": "2026 핵심 수주 프로젝트", "assignee_id": 5, "assignee_name": "정하나",
            "assignee_email": "hana.jung@argosworks.kr", "start_date": d_m5, "due_date": d_m1,
            "status": "완료", "card_code": "SALES-202", "priority": "긴급",
            "memo": "계약금 1,500만원 납품 계약서 체결 및 1년 무상 유지보수 협약 확정.",
            "jira_key": "SALES-202", "jira_status": "DONE"
        },
        {
            "id": base_id + 33, "dept_id": "sales", "category": "고객사미팅",
            "title": "금융권 고객사 폐쇄망 보안 실사 및 시스템 아키텍처 기술 브리핑",
            "project": "금융권 신규 개척", "assignee_id": 5, "assignee_name": "정하나",
            "assignee_email": "hana.jung@argosworks.kr", "start_date": d_m3, "due_date": d_p5,
            "status": "검토", "card_code": "SALES-203", "priority": "보통",
            "memo": "금융보안원 가이드라인 100% 준수 항목 증빙 보고서 제출.",
            "jira_key": "SALES-203", "jira_status": "IN_REVIEW"
        },
        {
            "id": base_id + 34, "dept_id": "sales", "category": "입찰제안",
            "title": "제조 대기업 대상 50 Seats 온프레미스 영구 라이선스 공급 제안서 작성",
            "project": "2026 핵심 수주 프로젝트", "assignee_id": 6, "assignee_name": "강동원",
            "assignee_email": "dongwon.kang@argosworks.kr", "start_date": d_today, "due_date": d_p7,
            "status": "검토", "card_code": "SALES-204", "priority": "보통",
            "memo": "초기 구축비용 및 24/7 기술지원 SLA를 포함한 TCO 3개년 비용 절감 분석표 작성 완료.",
            "jira_key": "SALES-204", "jira_status": "IN_REVIEW"
        },
        {
            "id": base_id + 35, "dept_id": "sales", "category": "기술지원",
            "title": "신규 고객사 온프레미스 서버 환경 점검 및 사전 설치 가이드 제공",
            "project": "고객 온보딩", "assignee_id": 6, "assignee_name": "강동원",
            "assignee_email": "dongwon.kang@argosworks.kr", "start_date": d_m3, "due_date": d_p2,
            "status": "진행", "card_code": "SALES-205", "priority": "보통",
            "memo": "고객사 IT팀과 포트 개방 및 Linux OS 호환성 사전 점검 진행.",
            "jira_key": "SALES-205", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 36, "dept_id": "sales", "category": "계약체결",
            "title": "2026 하반기 B2B 솔루션 파트너사 리셀러 협약 갱신",
            "project": "파트너십 강화", "assignee_id": 9003, "assignee_name": "MgrSales",
            "assignee_email": "mgrsales@test.com", "start_date": d_m7, "due_date": d_m1,
            "status": "완료", "card_code": "SALES-206", "priority": "높음",
            "memo": "국내 3개 총판 파트너십 계약 연장 및 기술 지원 마진율 협의 완료.",
            "jira_key": "SALES-206", "jira_status": "DONE"
        },
        {
            "id": base_id + 37, "dept_id": "sales", "category": "고객사미팅",
            "title": "주요 엔터프라이즈 고객사 분기 정례 만족도 조사 및 피드백 회의",
            "project": "고객관리", "assignee_id": 9003, "assignee_name": "MgrSales",
            "assignee_email": "mgrsales@test.com", "start_date": d_today, "due_date": d_p14,
            "status": "대기", "card_code": "SALES-207", "priority": "보통",
            "memo": "사용자 편의성 설문 분석 및 추가 기능 요구사항 정리.",
            "jira_key": "SALES-207", "jira_status": "TO_DO"
        },
        {
            "id": base_id + 38, "dept_id": "sales", "category": "기술지원",
            "title": "고객사 긴급 기술 문의 대응 및 패치 업데이트 가이드 배포",
            "project": "고객지원", "assignee_id": 9004, "assignee_name": "Mem",
            "assignee_email": "mem@argosworks.kr", "start_date": d_m3, "due_date": d_p2,
            "status": "진행", "card_code": "SALES-208", "priority": "높음",
            "memo": "버전 1.0.0 업그레이드 패키지 배포 및 현장 오류 원격 진단 지원.",
            "jira_key": "SALES-208", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 39, "dept_id": "sales", "category": "입찰제안",
            "title": "스마트팩토리 제안 견적서 산출 및 라이선스 매트릭스 검토",
            "project": "스마트팩토리 수주", "assignee_id": 9004, "assignee_name": "Mem",
            "assignee_email": "mem@argosworks.kr", "start_date": d_m7, "due_date": d_m1,
            "status": "완료", "card_code": "SALES-209", "priority": "보통",
            "memo": "센서 300대 및 게이트웨이 연동 하드웨어 패키지 견적서 발송 완료.",
            "jira_key": "SALES-209", "jira_status": "DONE"
        },

        # ==================== HR (인사총무·운영관리팀) ====================
        {
            "id": base_id + 41, "dept_id": "hr", "category": "채용",
            "title": "2026년 하반기 핵심 임베디드 및 백엔드 개발자 2명 온보딩 완료",
            "project": "인재영입 및 조직관리", "assignee_id": 7, "assignee_name": "한소영",
            "assignee_email": "soyoung.han@argosworks.kr", "start_date": d_m7, "due_date": d_m3,
            "status": "완료", "card_code": "HR-301", "priority": "보통",
            "memo": "사내 정보보호 서약서 징구, 개발 워크스테이션 지급 및 아르고스 워크스 전용 계정 권한 발급 완료.",
            "jira_key": "HR-301", "jira_status": "DONE"
        },
        {
            "id": base_id + 42, "dept_id": "hr", "category": "직무교육",
            "title": "전사 임직원 정보보호 가이드라인 및 사내 AI 비서 활용 세미나 개최",
            "project": "인재영입 및 조직관리", "assignee_id": 7, "assignee_name": "한소영",
            "assignee_email": "soyoung.han@argosworks.kr", "start_date": d_today, "due_date": d_p14,
            "status": "대기", "card_code": "HR-302", "priority": "보통",
            "memo": "외부 상용 AI 툴 보안사고 방지 및 사내 구축형 RAG 어시스턴트 활용법 전사 교육 준비.",
            "jira_key": "HR-302", "jira_status": "TO_DO"
        },
        {
            "id": base_id + 43, "dept_id": "hr", "category": "사내복지",
            "title": "사내 복지 포인트 제도 개편 및 종합 건강검진 지정 병원 확대 협약",
            "project": "복지 및 사내문화", "assignee_id": 7, "assignee_name": "한소영",
            "assignee_email": "soyoung.han@argosworks.kr", "start_date": d_m3, "due_date": d_p5,
            "status": "진행", "card_code": "HR-303", "priority": "보통",
            "memo": "2026 복지 만족도 조사 반영 및 전문 건강검진 센터 2곳 신규 제휴 협약 체결 진행.",
            "jira_key": "HR-303", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 44, "dept_id": "hr", "category": "인프라지원",
            "title": "연구소 및 영업팀 업무용 고성능 듀얼 모니터 및 사무 장비 지급",
            "project": "총무 및 시설지원", "assignee_id": 7, "assignee_name": "한소영",
            "assignee_email": "soyoung.han@argosworks.kr", "start_date": d_m5, "due_date": d_m1,
            "status": "완료", "card_code": "HR-304", "priority": "보통",
            "memo": "개발팀 인체공학 모니터 암 및 4K 모니터 전수 교체 지급 완료.",
            "jira_key": "HR-304", "jira_status": "DONE"
        },

        # ==================== HQ (품질관리·감사준법팀) ====================
        {
            "id": base_id + 51, "dept_id": "hq", "category": "내부감사",
            "title": "전사 4단계 권한 매트릭스(RBAC) 및 보안 감사 로그 무결성 전수 점검",
            "project": "상시 내부통제", "assignee_id": 8, "assignee_name": "윤재호",
            "assignee_email": "jaeho.yoon@argosworks.kr", "start_date": d_m5, "due_date": d_p5,
            "status": "진행", "card_code": "HQ-401", "priority": "높음",
            "memo": "최근 10,000건의 사용자 접속 및 데이터 변경 감사 로그 전수 검증 결과 위변조 없음 확인.",
            "jira_key": "HQ-401", "jira_status": "IN_PROGRESS"
        },
        {
            "id": base_id + 52, "dept_id": "hq", "category": "보안점검",
            "title": "온프레미스 서버 침입 탐지 및 방화벽 접근 제어 규칙 3분기 전수 점검",
            "project": "보안 컴플라이언스", "assignee_id": 8, "assignee_name": "윤재호",
            "assignee_email": "jaeho.yoon@argosworks.kr", "start_date": d_m3, "due_date": d_p2,
            "status": "검토", "card_code": "HQ-402", "priority": "긴급",
            "memo": "외부 인가되지 않은 IP 접근 차단 룰셋 검증 및 비인가 포트 전수 스캔 점검 완료.",
            "jira_key": "HQ-402", "jira_status": "IN_REVIEW"
        },
        {
            "id": base_id + 53, "dept_id": "hq", "category": "SLA검증",
            "title": "고객사 시스템 장애 대응 4시간 보장 SLA 분기 이행률 감사 보고",
            "project": "품질보증", "assignee_id": 8, "assignee_name": "윤재호",
            "assignee_email": "jaeho.yoon@argosworks.kr", "start_date": d_m7, "due_date": d_m1,
            "status": "완료", "card_code": "HQ-403", "priority": "보통",
            "memo": "지난 분기 장애 접수 12건 전원 평균 48분 이내 조치 완료 확인 (달성률 100%).",
            "jira_key": "HQ-403", "jira_status": "DONE"
        },
        {
            "id": base_id + 54, "dept_id": "hq", "category": "인증심사",
            "title": "정보보호 관리체계(ISMS/ISO 27001) 사후 심사 대비 증적 자료 취합",
            "project": "인증관리", "assignee_id": 8, "assignee_name": "윤재호",
            "assignee_email": "jaeho.yoon@argosworks.kr", "start_date": d_today, "due_date": d_p14,
            "status": "대기", "card_code": "HQ-404", "priority": "높음",
            "memo": "사내 보안 정책 준수율 점검 및 감사용 로그 보관 증빙 보고서 작성 진행 중.",
            "jira_key": "HQ-404", "jira_status": "TO_DO"
        }
    ]

    for r in records_to_insert:
        cur.execute("""
            INSERT INTO records (
                id, dept_id, category, title, project, assignee_id, assignee_name,
                assignee_email, start_date, due_date, work_date, summary, tags, memo,
                status, priority, card_code, participants, parent_key, is_scheduled,
                version, is_private, updated_at, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, '["엔터프라이즈","온프레미스","B2B"]', ?,
                ?, ?, ?, '', '', 1,
                1, 0, ?, ?
            )
        """, (
            r["id"], r["dept_id"], r["category"], r["title"], r["project"],
            r["assignee_id"], r["assignee_name"], r["assignee_email"],
            r["start_date"], r["due_date"], f"{r['start_date']} ~ {r['due_date']}",
            r["title"], r["memo"], r["status"], r["priority"], r["card_code"],
            now_iso, now_iso
        ))

        # Insert Jira mapping
        cur.execute("""
            INSERT INTO record_jira (record_id, jira_key, jira_status, jira_url)
            VALUES (?, ?, ?, ?)
        """, (
            r["id"], r["jira_key"], r["jira_status"],
            f"https://jira.internal.argosworks.kr/browse/{r['jira_key']}"
        ))

    # 3. Add realistic sample comments
    sample_comments = [
        (base_id + 1, "김민수", "재무기획팀 및 인프라팀과 사전 조율 완료했습니다. Q1 집행 일정 확정하겠습니다.", now_iso),
        (base_id + 11, "이도현", "서버 랙 구축 및 DMZ 분리 설정 완료되었습니다. 10Gbps 백본 지연시간 0.28ms로 측정되었습니다.", now_iso),
        (base_id + 13, "박서준", "마스터 키는 HSM 전용 격리 공간에 보관되었으며 복호화 권한 검증 테스트 성공했습니다.", now_iso),
        (base_id + 15, "최유진", "vLLM 로컬 추론 벤치마크 결과 7B 모델 응답 시간 평균 650ms로 측정되었습니다.", now_iso),
        (base_id + 31, "정하나", "고객사 CISO 인터뷰에서 클라우드 SaaS 대비 온프레미스 격리망 안정성에 대해 최고 평가를 받았습니다.", now_iso),
        (base_id + 41, "한소영", "신규 입사자 계정 및 장비 지급 완료되었으며 멘토링 프로그램 배정 완료했습니다.", now_iso),
        (base_id + 51, "윤재호", "최근 3개월간 감사 로그 해시 체인 무결성 전수 검증 통과했습니다. 이상 징후 0건입니다.", now_iso)
    ]
    cur.executemany("""
        INSERT INTO record_comments (record_id, author_name, body, created_at)
        VALUES (?, ?, ?, ?)
    """, sample_comments)

    # 4. Update card_sequences
    sequences = [
        ("mgmt", 105),
        ("dev", 115),
        ("sales", 210),
        ("hr", 305),
        ("hq", 405)
    ]
    for s in sequences:
        cur.execute("""
            INSERT INTO card_sequences (dept_id, last_seq)
            VALUES (?, ?)
            ON CONFLICT(dept_id) DO UPDATE SET last_seq = excluded.last_seq
        """, s)

    conn.commit()
    conn.close()
    print(f"Successfully seeded {len(records_to_insert)} records across all 5 departments!")

if __name__ == "__main__":
    seed()
