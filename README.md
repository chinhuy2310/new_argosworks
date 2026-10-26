# ARGOS WORKS — 프로젝트 구조 및 파일 명세서

본 문서는 **ARGOS WORKS** 시스템의 전체 아키텍처, 디렉터리 구조 및 각 파일의 상세 기능과 역할을 설명합니다.

---

## 🚀 빠른 시작 (Quick Start)

### 실행 요구사항
- **Python 3.10 이상** (검증 환경: Python 3.12)
- **의존성 설치 필수**: `pip install -r requirements.txt`
  (cryptography, openpyxl, pillow, psycopg2-binary, waitress/gunicorn)
- 권장: **PostgreSQL 14+** (20~30명 초과 시), 소규모는 SQLite 파일 모드 사용 가능
- **웹 브라우저** (Chrome, Edge 등 모던 브라우저)

### 실행 방법 (개발/데모)
1. 의존성 설치 후 루트의 `run_server.bat`(Windows) 또는 아래 명령을 실행합니다.
   ```bash
   pip install -r requirements.txt
   python server/main.py
   ```
2. 콘솔 창에 서버 시작 메시지가 출력되면 웹 브라우저에서 아래 주소로 접속합니다:
   - **접속 주소**: `http://localhost:8080/` (최초 1회는 `/setup.html`에서 라이선스/관리자 생성)

### 실행 방법 (고객사 운영 환경)
```bash
cp .env.example .env          # ARGOS_MASTER_KEY(필수), DATABASE_URL, DOMAIN 설정
docker compose up -d --build  # App + Caddy(HTTPS) + PostgreSQL
```
운영 배포·서비스 등록·백업·라이선스 발급 절차는
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)와 [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md)를 참조하십시오.

---

## 📂 프로젝트 전체 디렉터리 트리 (Project Tree)

```text
argoswork/
│
├── 📄 run_server.bat                           # [실행] Windows 원클릭 서버 실행 배치 스크립트
├── 📄 run_tests.bat / run_tests.sh             # [테스트] pytest + unittest 실행 게이트
├── 📄 .env                                     # [설정] 환경변수 및 Master Key
├── 📄 .env.example                             # [설정] 환경변수 템플릿 예시 파일
├── 📄 README.md                                # [문서] 프로젝트 아키텍처 및 파일 명세서 (본 파일)
│
├── 📂 server/                                  # [백엔드] Python 경량 HTTP 서버 및 비즈니스 로직
│   ├── 📄 main.py                              # 서버 진입점 (ThreadingHTTPServer 포트 시작 및 백그라운드 서비스)
│   ├── 📄 handler.py                           # HTTP 요청 처리 기본 핸들러 (SSE 스트리밍, 정적 파일 서빙, 세션 인증)
│   ├── 📄 router.py                            # URL 라우팅 테이블 (GET/POST 엔드포인트 디스패처)
│   ├── 📄 config.py                            # 서버 설정 로더 (.env 우선 로드, 기본 설정값, 디렉터리 경로 상수)
│   ├── 📄 config.example.json                  # JSON 설정 템플릿 파일 (Jira URL, AI 공급자/모델 정보 등)
│   ├── 📄 db.py                                # SQLite 데이터베이스 인터페이스 (WAL 모드, 트랜잭션, 커넥션 풀)
│   ├── 📄 schema.sql                           # SQLite 데이터베이스 스키마 정의 파일
│   │
│   ├── 📂 handlers/                            # [API 컨트롤러] 웹 요청 수신 및 응답 처리
│   │   ├── 📄 chat_handler.py                  # AI 챗봇 API (SSE 스트리밍 대화, 세션 CRUD, 액션 제안 실행)
│   │   ├── 📄 auth_handlers.py                 # 계정 인증 API (사용자 확인, 회원가입, 로그인)
│   │   ├── 📄 submit_handler.py                # 업무/티켓 등록 API (멀티파트 첨부파일 업로드, AI 카테고리 자동 분류)
│   │   ├── 📄 product_handlers.py              # 사내 PIM 제품/자산 관리 API
│   │   ├── 📄 schedule_handlers.py             # 일정 관리 API (연차/반차/출장/회의 일정 CRUD)
│   │   ├── 📄 department_handler.py            # 부서 관리 API (신규 부서 추가 및 목록 조회)
│   │   ├── 📄 report_handler.py                # 주간/월간 엑셀 업무보고서 템플릿 엔진 API
│   │   ├── 📄 sync_handler.py                  # Jira 즉시 동기화 API
│   │   └── 📄 settings_handler.py              # 환경설정 API (AI/Jira/Workspace 설정 저장 및 연결 테스트)
│   │
│   ├── 📂 services/                            # [비즈니스 서비스] 도메인 로직 및 외부 연동
│   │   ├── 📄 chat_agent.py                    # ReAct 멀티턴 AI 에이전트 대화 루프 (자율 도구 호출 및 답변 합성)
│   │   ├── 📄 chat_tools.py                    # AI 에이전트용 도구 정의 (이슈 검색, 벡터 검색, 일정 조회 등)
│   │   ├── 📄 chat_store.py                    # 챗봇 세션 및 메시지 이력 관리
│   │   ├── 📄 ai_client.py                     # 범용 LLM 클라이언트 (Google Gemini, OpenAI, Claude, Ollama 연동)
│   │   ├── 📄 vector_store.py                  # 임베딩 & 로컬 SQLite 벡터 검색 엔진 (Semantic Search / RAG)
│   │   ├── 📄 jira_client.py                   # Jira Cloud REST API 연동 (JQL 검색, 상태 변경, 댓글, 첨부파일, 캐시)
│   │   ├── 📄 sheets_reporter.py               # 커스텀 엑셀 템플릿 기반 보고서 생성 엔진
│   │   ├── 📄 data_store.py                    # SQLite 기반 내부 데이터 관리 (부서, 제출 기록, 일정, 제품)
│   │   ├── 📄 auth.py                          # 비밀번호 암호화(PBKDF2-HMAC-SHA256) 및 세션 토큰 관리
│   │   ├── 📄 product_manager.py               # 사내 제품/자산 정보 검색 및 유효성 검증
│   │   ├── 📄 search.py                        # 통합 키워드 검색 엔진 (이슈 + 제품 + 일정)
│   │   └── 📄 activity_store.py                # 사내 업무 이력 및 일일 활동 로그 기록/조회 (관리자용)
│   │
│   └── 📂 utils/                               # [공통 유틸리티] 보조 헬퍼 모듈
│       ├── 📄 crypto.py                        # AES-256 + HMAC-SHA256 비밀 키/토큰 보안 암호화
│       ├── 📄 logging.py                       # 콘솔 표준 출력 로그 및 일별 CSV 접속 로그 기록
│       ├── 📄 file_ops.py                      # 파일명 살균(Sanitize), 고유 첨부파일명 생성, 원자적 쓰기
│       ├── 📄 multipart.py                     # 외부 패키지 없는 순수 Python 멀티파트 폼데이터 파서
│       └── 📄 text.py                          # 텍스트 변환, 담당자명 정규화, 날짜 파싱 유틸
│       ├── 📄 logging.py                       # 콘솔 표준 출력 로그 및 일별 CSV 접속 로그(access_*.csv) 기록
│       ├── 📄 file_ops.py                      # 파일명 살균(Sanitize), 고유 첨부파일명 생성, 원자적(Atomic) 파일 쓰기
│       ├── 📄 multipart.py                     # 외부 패키지 없는 순수 Python 멀티파트 폼데이터(multipart/form-data) 파서
│       └── 📄 text.py                          # Jira ADF 텍스트 변환, 담당자명 정규화, 날짜 파싱 유틸
│
├── 📂 web/                                     # [프론트엔드] Single Page Application (HTML/CSS/JS 순수 웹 표준)
│   ├── 📄 index.html                           # 메인 SPA 통합 마크업 및 캔버스 패널 모달 템플릿
│   ├── 📄 favicon.svg                          # 브라우저 탭 아이콘
│   │
│   ├── 📂 css/                                 # [스타일시트] 모듈별 CSS 파일
│   │   ├── 📄 variables.css                    # 전역 디자인 시스템 변수, 테마 컬러 팔레트 (다크/라이트 모드)
│   │   ├── 📄 layout.css                       # 공통 상단 탑바(Topbar), 로고, 탭 네비게이션, 사용자 영역
│   │   ├── 📄 home.css                         # 홈 탭 스타일 (구글형 중앙 검색창, 인터랙티브 캔버스 배경)
│   │   ├── 📄 dashboard.css                    # 대시보드 탭 (부서별 카드, 칸반/테이블 그리드, 트리 뷰 계층 구조)
│   │   ├── 📄 chat.css                         # AI 챗봇 탭 (사이드바 대화 목록, 말풍선, 캔버스 연동 화면 분할)
│   │   ├── 📄 canvas.css                       # 아티팩트 캔버스 스타일 (📌 고정 분할, 🗂️ 오버레이 슬라이드, ⛶ 중앙 모달)
│   │   ├── 📄 calendar.css                     # 일정 탭 스타일 (월간 캘린더 그리드, 휴가/출장 배지, Jira 마감일)
│   │   ├── 📄 pim.css                          # 제품정보 탭 스타일 (공식 카탈로그 그리드, 제품 규격서 모달)
│   │   ├── 📄 form.css                         # Jira 티켓 등록 탭 (드롭존 파일 첨부 UI, 폼 필드)
│   │   ├── 📄 history.css                      # 업무 이력 탐색기 스타일 (타임라인 활동 로그, 필터)
│   │   ├── 📄 settings.css                     # API 환경설정 탭 스타일 (AI/Voyage/Jira 상태 카드 및 연결 테스트 UI)
│   │   └── 📄 components.css                   # 공통 컴포넌트 스타일 (토스트 알림, 모달 팝업, 버튼, 배지)
│   │
│   └── 📂 js/                                  # [스크립트] 모듈별 순수 자바스크립트 로직
│       ├── 📄 utils.js                         # 공통 유틸리티 (DOM 캐싱, escapeHtml, showToast, 포맷터)
│       ├── 📄 api.js                           # 인증 헤더 자동 첨부 HTTP 통신 클라이언트 (apiGet, apiPostJson)
│       ├── 📄 auth.js                          # 사용자 로그인/로그아웃 상태 관리 및 세션 복원
│       ├── 📄 dashboard.js                     # Jira 이슈 카드 렌더링, 필터링, 담당자별 뷰 및 트리 뷰 토글
│       ├── 📄 jira-form.js                     # Jira 티켓 생성 폼 제출, 드래그앤드롭 파일 첨부 처리
│       ├── 📄 calendar.js                      # 캘린더 월간 일정 렌더링, Jira 일정 연동, 개인/팀 일정 CRUD
│       ├── 📄 home.js                          # 홈 화면 빠른 질의응답 및 인터랙티브 배경 파티클 애니메이션
│       ├── 📄 pim.js                           # PIM 제품 검색, 공식 웹 제품 크롤링 뷰, 규격 관리 로직
│       ├── 📄 history.js                       # 일일 업무 활동 이력 날짜별 조회 및 렌더링 (관리자 전용)
│       ├── 📄 settings.js                      # AI/Jira 설정 저장, Voyage 벡터 재색인, 실시간 헬스체크
│       ├── 📄 chat.js                          # SSE 기반 AI 스트리밍 대화 수신, 타이핑 효과, 세션 관리
│       ├── 📄 canvas.js                        # 캔버스 이슈 상세 보기, 3가지 뷰 모드 전환, 상태 변경, 댓글/첨부파일
│       └── 📄 app.js                           # SPA 탭 라우팅(showTab), URL 해시 제어, 탭 전환 시 캔버스 자동 닫기
│
├── 📂 data/                                    # [데이터베이스 및 저장소]
│   ├── 📄 argos.db                             # SQLite 메인 DB (계정, 부서, 작업 기록, 캘린더 일정, PIM 제품 등)
│   ├── 📄 vector_store.sqlite                  # Voyage AI 기반 시맨틱 검색용 로컬 벡터 데이터베이스 (95+ 벡터 내장)
│   ├── 📄 chat_sessions.json                   # 챗봇 세션 메타데이터 목록 (세션 ID, 제목, 사용자, 생성일)
│   ├── 📂 chat_history/                        # 개별 세션별 대화 메시지 기록 파일 디렉터리 (*.jsonl)
│   └── 📂 attachments/                         # 사용자가 업로드한 로컬 첨부파일 저장 디렉터리
│
└── 📂 logs/                                    # [접속 로그 디렉터리]
    └── 📄 access_YYYYMMDD.csv                  # 일자별 요청 접속 기록 (IP, 작업명, 상태코드, 상세)
```

---

### 1.0.0에서 추가/변경된 파일 (문서 트리 보완)

```text
├── 📄 VERSION                              # 릴리스 버전 (1.0.0, /api/version 및 설정 하단에 표시)
├── 📄 CHANGELOG.md                         # SemVer 변경 이력 (Keep a Changelog)
├── 📄 requirements-dev.txt                 # 테스트 의존성 (pytest, pytest-cov)
├── 📄 pytest.ini / run_tests.bat / .sh     # 테스트 실행 게이트
├── 📂 deploy/                              # systemd unit, Windows 서비스 설치 스크립트
├── 📂 licenses/                            # 발급된 .lic (trial-50.lic 포함)
├── 📂 tools/vendor/                        # [Vendor 전용] license_tool.py (고객 배포 제외)
├── 📂 tests/                               # pytest + unittest (325 케이스)
└── 📂 server/
    ├── 📄 module_gate.py                   # 라이선스 모듈 권한 게이트 (PIM/Jira/RAG/Schedule/Audit)
    ├── 📄 wsgi.py                          # waitress/gunicorn WSGI 진입점
    ├── 📄 middleware_security.py           # Rate limit, CSRF, CORS
    └── 📂 services/                        # license_manager, audit_logger, backup_manager,
                                            # sso_provider, notification_service, webhook_dispatcher 등
```

---

## 🛠️ 주요 모듈별 상세 설명

### 1. 백엔드 아키텍처 (`server/`)
- **경량 코어 + 최소 의존성**: HTTP 서버/라우팅/템플릿은 Python 표준 라이브러리(`http.server`, `urllib`, `sqlite3`, `threading`)로 구현하고, 표준 라이브러리로 대체할 수 없는 부분만 외부 패키지로 고정했습니다(`cryptography` 암호화, `openpyxl` Excel 보고서, `pillow` 이미지 최적화, `psycopg2` PostgreSQL, `waitress`/`gunicorn` WSGI). 무거운 프레임워크(Flask/FastAPI/ORM)는 사용하지 않습니다.
- **RAG & 시맨틱 검색 (`vector_store.py`)**: 별도의 벡터 DB 서버(Pinecone, Milvus 등) 구축 없이 `vector_store.sqlite`에 BLOB 형태로 임베딩을 저장하고 Cosine Similarity를 계산하여 빠른 지식 검색을 지원합니다.
- **AI ReAct 에이전트 (`chat_agent.py` & `chat_tools.py`)**: 사용자의 요청 언어를 감지하여 이슈 조회, 일정 확인, 지식 검색 등의 도구를 자율적으로 호출한 뒤 종합된 답변을 스트리밍(SSE)으로 제공합니다.

### 2. 프론트엔드 아키텍처 (`web/`)
- **순수 웹 표준 (Pure Vanilla Stack)**: 빌드 툴(Webpack, Vite)이나 프레임워크(React, Vue) 없이 동작하여 유지보수와 배포가 매우 간편합니다.
- **인터랙티브 캔버스 (`canvas.js` & `canvas.css`)**: 이슈 클릭 시 우측에 독립된 작업 공간이 열리며, 사용자의 취향에 따라 **📌 고정 분할 (Docked Split Screen)**, **🗂️ 슬라이드 오버레이 (Overlay)**, **⛶ 중앙 모달 (Modal)**의 3가지 디스플레이 모드를 자유롭게 전환할 수 있습니다.
- **지능형 화면 반응형 (Responsive)**: 챗봇 탭에서 캔버스를 고정 분할 모드로 열 경우 채팅창이 자동으로 좌측으로 축소되어 채팅과 상세 업무를 동시에 병행할 수 있습니다.

---

## License (상용 배포)

- 고객 인스턴스에는 **공개키만** 포함되며, 개인키(서명키)는 벤더가 오프라인으로 보관합니다.
- 라이선스 = 고객사명 + 좌석(seats) + 만료일 + 모듈 목록을 담은 **Ed25519 서명 토큰**.
- 모듈(`pim`, `jira`, `rag`, `schedule`, `audit`)이 라이선스에 없으면 해당 API는 **403**으로 차단됩니다.
- 만료 시 **읽기 전용**으로 전환되며 고객 데이터는 삭제되지 않습니다.

```bash
# [Vendor 전용] 발급
python tools/vendor/license_tool.py issue \
    --customer "ACME" --seats 40 --expiry 2027-12-31 \
    --modules canvas,pim,jira,rag,schedule,audit --out licenses/ACME-2027.lic

# [고객] 오프라인 활성화 (UI 미사용 시)
python scripts/apply_license.py licenses/trial-50.lic --db data/argos.db
```

## 테스트 & CI

```bash
pip install -r requirements-dev.txt
python -m pytest -q              # unit / integration / e2e
python -m unittest discover -s tests -v   # 레거시 감사/RBAC/WSGI 스위트
```

CI(`.github/workflows/ci.yml`)는 위 두 스위트 + coverage + `compileall` + `node --check` +
Bandit/pip-audit/Trivy/SBOM를 실행합니다.

## 릴리스 패키징

```bash
python scripts/build_release.py --include-docs
# -> dist/argos-works-<VERSION>.zip
```

스크립트는 `data/`, `logs/`, `server/config.json`, `*.db`, `tools/vendor/`, `tests/`를 제외하며,
**서명키나 DB 파일이 포함되면 빌드를 중단**합니다.

## 문서 색인

| 문서 | 대상 |
|---|---|
| [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) | IT 관리자 (설치·RBAC·라이선스·백업·업그레이드) |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | 최종 사용자 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | DevOps (Docker/HTTPS/서비스 등록/릴리스/라이선스 발급) |
| [docs/SECURITY_WHITEPAPER.md](docs/SECURITY_WHITEPAPER.md) | CISO/CTO (보안 모델 + 알려진 한계) |
| [docs/SLA.md](docs/SLA.md) | 지원 등급(P1–P3) 및 책임 범위 |
| [docs/EULA.md](docs/EULA.md) | 라이선스 계약 및 데이터 처리 |
| [docs/COMMERCIAL_PRODUCT_CHECKLIST.md](docs/COMMERCIAL_PRODUCT_CHECKLIST.md) | 상용화 체크리스트 현황 |

