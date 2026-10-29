# ARGOS WORKS — Danh mục chỉnh sửa để thành sản phẩm thương mại

Tài liệu này liệt kê **các hạng mục cần sửa** để ARGOS WORKS có thể bán cho công ty / doanh nghiệp (on-premise).  
Trạng thái hiện tại: **MVP nội bộ / demo** — chưa phải commercial product hoàn chỉnh.

Cách dùng: tick từng mục khi hoàn thành. Ưu tiên **P0 → P1 → P2**. Không bắt đầu P2 khi P0 còn mở.

---

## 📌 Trạng thái cập nhật — bản 1.0.0 (2026-10-23)

Đã hoàn thành trong bản 1.0.0 (xem `CHANGELOG.md`):

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| P0.1–P0.5 Bảo mật/tài khoản/bí mật/pháp lý | ✅ | Như checklist bên dưới |
| P1.1 RBAC (4 role, kiểm tra phía server, PIM giá) | ✅ | `services/auth.py`, `tests/test_rbac_*` |
| P1.3 Audit + **export CSV/JSON** | ✅ | `AUDIT_EXPORT`, `/api/admin/audit-logs/export` |
| P1.4 Health check / WSGI / Postgres / **service manager** | ✅ | `deploy/argos-works.service`, `deploy/install_windows_service.ps1` |
| P1.6 Kiểm thử + CI gate | ✅ | pytest + unittest + coverage trong CI; 300+ test |
| P2.1 Setup wizard + tài liệu IT/user | ✅ | `docs/ADMIN_GUIDE.md`, `docs/USER_GUIDE.md`, `docs/SECURITY_WHITEPAPER.md` |
| P2.2 License: Ed25519, ghế, hạn, module, offline, **UI admin** | ✅ | Rotate khoá; enforce module; UI tab 🔑 License |
| P2.4 Semver / CHANGELOG / migration an toàn | ✅ | `VERSION`, `CHANGELOG.md`, `/api/version` |
| P2.3 i18n tiếng Việt | ❌ **Còn mở** | UI hiện KO/EN; cần thêm `vi` (B10) |
| P1.2 MFA/LDAP/invite | ❌ **Còn mở** | SSO OIDC có module nền tảng |
| P1.5 Thư viện chuẩn (bỏ AES tự viết) | 🟡 | Đã dùng `cryptography` cho license; luồng AES nội bộ vẫn giữ |
| P3 Pentest/SOC2/HA | ❌ Chưa | Khuyến nghị trước khi bán tập đoàn |

**Điều kiện bán SME hiện đã đạt 6/7** — mục còn thiếu là i18n tiếng Việt cho khách Việt (không chặn khách KO/EN).

---


## 0. Định hướng (không đổi kiến trúc cốt lõi)

- [ ] Giữ mô hình **on-premise, 1 khách = 1 instance**. Không chuyển SaaS đa tenant ở giai đoạn đầu.
- [ ] Bán như **lớp tri thức + bàn giao kỹ thuật** (canvas, RAG, lịch, PIM), **không** bán như thay thế Jira.
- [ ] Tách rõ **bản nguồn nội bộ** và **bản giao khách** (không dính dữ liệu / connector / alias của một công ty).

---

## P0 — Chặn ký hợp đồng / không được đưa vào mạng khách (ĐÃ HOÀN THÀNH 100%)

### P0.1 Bảo mật API và phiên đăng nhập

- [x] Bắt buộc đăng nhập cho **mọi** `/api/*` trừ health check và login/register (register sẽ tắt — xem P0.2).
- [x] Khóa các endpoint hiện đang đọc công khai:
  - `/api/records`, `/api/records/hierarchy`
  - `/api/members`, `/api/departments`, `/api/categories`
  - `/api/products`, `/api/products/detail`, `/api/products/attachment`
  - `/api/ask`
  - `/api/schedule`
  - `/api/attachments/*`, `/api/jira/attachments/*`
  - `/api/issues*`
  - `/api/notifications*` (không cho đọc/đánh dấu đã đọc khi chưa login; kiểm tra đúng chủ sở hữu)
  - `/api/vectors/stats`
- [x] Session có **TTL thật** (đề xuất 8–24 giờ), không chỉ cookie `Max-Age=30 ngày` (Mặc định 24h, cấu hình qua `SESSION_TTL_HOURS`).
- [x] `get_session()` từ chối token hết hạn; dọn session cũ (Tự động xóa session hết hạn khi truy cập và chạy background thread hàng giờ).
- [x] Logout xóa session server-side (đã có) + cookie; thêm **logout mọi thiết bị** (`POST /api/account/logout-all`).
- [x] Rate-limit + khóa tạm tài khoản khi login sai nhiều lần (theo IP và theo user: khóa 15 phút sau 5 lần thử sai).
- [x] CSRF token / SameSite=Lax/Strict + HttpOnly + Secure headers phòng chống XSS & F12 token theft.
- [x] Không trả raw exception ra client (`handler.py` ẩn traceback `str(e)` ở HTTP 500, log nội bộ tại server).

### P0.2 Tài khoản và mật khẩu

- [x] **Tắt tự đăng ký** mặc định (`/api/account/register`). Chỉ admin tạo / mời user.
- [x] Cờ cấu hình `ALLOW_PUBLIC_REGISTER=false` (chỉ bật cho demo có kiểm soát).
- [x] Policy mật khẩu: tối thiểu 8 ký tự, từ chối mật khẩu ngắn dưới 8 ký tự.
- [x] Không tự phong admin cho user đầu theo cách khó kiểm soát; phân quyền admin rõ ràng trong DB (`users.is_admin`).
- [x] Vô hiệu hóa / khóa user (disable) mà không xóa dữ liệu lịch sử (`acc.get("disabled")`).

### P0.3 Bí mật, cấu hình, git

- [x] Không lưu API key plaintext trong `server/config.json`.
- [x] Chỉ dùng `.env` (hoặc secret store); `config.json` chỉ còn giá trị không nhạy cảm.
- [x] Thêm `.gitignore`: `.env`, `data/*.db`, `data/*.sqlite`, `logs/`, backup, `server/config.json` nếu chứa secret.
- [x] Thêm `.env.example` đủ field, không có giá trị thật.
- [x] **Rotate** mọi key AI / Jira / embedding đã từng nằm trong repo hoặc máy demo.
- [x] Không commit DB, vector store, chat history, attachments vào git.

### P0.4 Tách “bản một công ty” khỏi sản phẩm

- [x] Xóa / chuyển `NAME_ALIASES` nhân sự cứng trong `router.py` thành đối chiếu động từ bảng tài khoản hệ thống.
- [x] Đưa connector Vision119 ra module **tùy chọn**, tắt mặc định trên bản giao khách.
- [x] `config.json` / seed không chứa URL Jira, email, project key của cá nhân / nội bộ.
- [x] Đổi branding còn sót: `JarvisHandler` → `ArgosHandler`, log “JARVIS” → “Argos”, `server_version` → `ArgosServer/2.0`.
- [x] Bản giao khách: DB độc lập, không hardcode danh sách người của một công ty duy nhất.

### P0.5 Pháp lý tối thiểu

- [x] `LICENSE` (mã nguồn nội bộ / giấy phép thương mại) + **EULA** cho khách on-prem (`docs/EULA.md`).
- [x] Điều khoản xử lý dữ liệu (DPA) / cam kết 100% dữ liệu nằm tại máy khách.
- [x] Chính sách backup, lưu trữ, xóa dữ liệu khi hết hợp đồng.
- [x] Không thu thập telemetry mặc định; nếu có thì opt-in (Zero Default Telemetry).

---

## P1 — Doanh nghiệp sẽ hỏi trong POC

### P1.1 Phân quyền (RBAC)

- [x] Nhiều hơn `admin` / `member` (đã triển khai, dùng `manager` thay cho `dept_admin`):
  - `admin` — hệ thống, user, backup, settings, license
  - `manager` (`dept_admin`) — quản lý phòng mình, duyệt trạng thái
  - `member` — tạo/sửa việc được giao hoặc phòng mình
  - `viewer` — chỉ đọc
- [x] Kiểm tra quyền **phía server** (không chỉ ẩn tab UI) — `can_view_record`, `can_modify_record`, `can_delete_record`.
- [x] Phân tách dữ liệu theo phòng: member không đọc toàn bộ công ty nếu policy không cho.
- [x] PIM / SPEC: quyền xem giá, tài liệu firmware riêng (`can_view_pim_price`, `can_modify_pim`).

### P1.2 Đăng nhập doanh nghiệp

- [ ] SSO: OIDC (Google Workspace / Azure AD / Keycloak) — 🟡 có module nền tảng `sso_provider.py`, **chưa nối vào luồng đăng nhập**.
- [ ] Tùy chọn LDAP / Active Directory (nhiều nhà máy vẫn dùng) — chưa có.
- [ ] MFA cho tài khoản admin (TOTP) — chưa có trong 1.0.0.
- [ ] Invite bằng email hoặc mã một lần nếu không có SSO — hiện Admin tạo user trực tiếp.

### P1.3 Audit và tuân thủ

- [x] Nhật ký kiểm toán: login, thất bại login, tạo/sửa/xóa record, đổi quyền, backup/restore, đổi license, export audit.
- [x] Audit không ghi mật khẩu / API key (`log_audit` che `password|token|hash|salt|api_key|secret`).
- [x] Xuất audit (CSV/JSON) theo khoảng ngày — `/api/admin/audit-logs/export` (UTF-8 BOM, chống CSV injection).
- [x] Giữ access log hiện tại nhưng **không** dùng làm audit duy nhất.

### P1.4 Vận hành và tải

- [x] Xác định ngưỡng: SQLite + `ThreadingHTTPServer` chấp nhận được cho ~20–30 user đồng thời (ghi trong `docs/ADMIN_GUIDE.md` mục 2).
- [x] Trên ngưỡng: tùy chọn PostgreSQL + server WSGI (`waitress`/`gunicorn`) sau reverse proxy.
- [x] Health check không lộ phiên bản / cấu hình nhạy cảm (`/api/health` chỉ trả ok/status/time/database; `/api/version` riêng).
- [x] Header bảo mật trên **cả** Python server (không chỉ Caddy): HSTS khi HTTPS, `X-Content-Type-Options`, `X-Frame-Options` / CSP, `Referrer-Policy`.
- [x] Giới hạn kích thước body (`max_upload_mb`, trả 413) + rate limit theo IP; body lớn spool ra disk.
- [x] Backup restore: test tự động round-trip (`tests/test_backup_restore.py`), luôn tạo safety snapshot, có runbook trong Admin Guide.
- [x] Windows Service (scheduled task/NSSM) + systemd unit (`deploy/`).

### P1.5 Mã hóa và thư viện

- [x] Không còn AES tự viết: `utils/crypto.py` dùng thư viện `cryptography` (AES-256 + HMAC-SHA256, encrypt-then-MAC).
- [x] `requirements.txt` pin phiên bản; README ghi rõ đã có dependency thay vì “zero dependency”.
- [x] Quét dependency (CVE) trước mỗi bản phát hành: pip-audit + Bandit + Trivy trong CI.

### P1.6 Kiểm thử

- [x] Test tự động: login, register tắt, API 401 khi chưa login, RBAC 403, backup/restore (325 test: pytest + unittest).
- [ ] Test không lộ secret trong response settings (mask key) — **chưa có test tự động** (code đã mask trong `settings_handler._mask_value`).
- [x] CI gate trên mỗi push/PR (pytest + unittest + coverage + Bandit/pip-audit/Trivy); chưa cấu hình riêng cho tag.

---

## P2 — Đóng gói để bán (productization)

### P2.1 Cài đặt và onboarding

- [x] Wizard lần đầu: tạo admin, khai báo công ty/phòng ban, xác thực license (`web/setup.html` + `setup_handler.py`).
- [x] Tài liệu IT (~10 trang): `docs/ADMIN_GUIDE.md` (Docker, HTTPS, backup, firewall, nâng cấp, xử lý sự cố).
- [x] Tài liệu user: `docs/USER_GUIDE.md` (đăng nhập, tạo việc, canvas, lịch, hỏi AI).
- [x] Môi trường demo: `scripts/seed_demo_data.py` (dữ liệu giả) + `ARGOS_FRESH_INSTALL=1` xoá seed demo khi cài khách.

### P2.2 Giấy phép phần mềm

- [x] License key: tên công ty, số ghế, ngày hết hạn, module — ký **Ed25519**, ghế/hạn đọc từ payload đã ký.
- [x] Admin UI hiện trạng thái license (Settings → 🔑 라이선스).
- [x] Chặn tạo/duyệt user khi vượt số ghế hoặc license không hợp lệ.
- [x] Kích hoạt **offline**: dán key trong UI hoặc `python scripts/apply_license.py <file>.lic`.
- [x] Cảnh báo trước ngày hết hạn (30 ngày); hết hạn chuyển chỉ-đọc, **không** khoá/xoá dữ liệu.
- [x] Trial licence có thời hạn `term_days` (mặc định 60 ngày) tính **từ lần kích hoạt đầu tiên**, neo `license_info.activated_at`, không cần hạn cứng; kích hoạt lại cùng key hoặc lùi đồng hồ hệ thống đều **không** kéo dài (`last_seen_ts` high-water mark).

### P2.3 White-label và i18n

- [ ] Workspace name / logo / footer (đã có mầm) — hoàn thiện trên login + PDF/Excel.
- [ ] i18n **tiếng Việt đầy đủ** (hiện KO/EN; UI/backend còn nhiều chuỗi tiếng Hàn cứng).
- [ ] Chuẩn hóa status (`진행` / Done…) thành mã nội bộ + nhãn theo ngôn ngữ.

### P2.4 Nâng cấp và hỗ trợ

- [x] Semver (`VERSION` = 1.0.0), `CHANGELOG.md` (có mục BREAKING về rotate license key), `/api/version`.
- [x] Migration `schema.sql` an toàn: `init_db()` áp schema + migration theo version, không xoá bảng/cột; có test PostgreSQL/SQLite.
- [x] Gói patch; rollback từ backup (quy trình trong `docs/ADMIN_GUIDE.md` mục 7).
- [x] Kênh hỗ trợ + SLA theo gói: `docs/SLA.md` (P1/P2/P3, Standard vs Premium).
- [x] Không ghi đè `data/`: `scripts/build_release.py` loại `data/`, `logs/`, `server/config.json`; hướng dẫn nâng cấp giữ nguyên `data/`.

### P2.5 AI / RAG sản phẩm hóa

- [x] Air-gap: Ollama (LLM) + embedding local/LAN, không bắt buộc gọi cloud.
- [x] Cảnh báo dữ liệu gửi lên AI cloud: ghi trong `docs/EULA.md` (2.2) và `docs/b2b-commercial-internal-software.md` (mục 5).
- [ ] Giới hạn chi phí / timeout / kích thước context — đã **theo dõi** token/chi phí (`ai_usage_service`), chưa có hard-cap.
- [x] Công cụ agent không vượt quyền: `visible_records` + `can_modify_record` + mask giá PIM trước khi trả kết quả.

---

## P3 — Tập đoàn / vòng bảo mật lớn (sau khi đã bán được SME)

- [ ] Pentest bên thứ ba + vá finding trước GA.
- [ ] Tùy chọn PostgreSQL HA, backup offsite.
- [ ] SAML đầy đủ, SCIM provisioning user.
- [ ] Phân loại dữ liệu (nội bộ / mật / đối tác).
- [ ] Retention policy (xóa tự động chat / log sau N ngày).
- [ ] SOC2 / ISO 27001 (nếu bán thị trường US/EU hoặc tập đoàn lớn).
- [ ] Portal khách: ticket, download bản vá, license.

---

## Thứ tự thực hiện đề xuất

| Pha | Thời gian ước lượng | Mục tiêu |
|---|---|---|
| **1. Khóa an toàn** | 2–3 tuần | Hết P0: auth API, tắt register, session, rate-limit, gitignore, rotate key, ẩn exception, tách data nội bộ |
| **2. Gói SME** | 4–6 tuần | P1 RBAC + audit + P2 installer/license/tài liệu |
| **3. Doanh nghiệp** | 8–12 tuần | SSO, MFA, PostgreSQL option, pentest, EULA/DPA, Ollama air-gap |
| **4. Mở rộng** | Liên tục | i18n VI, connector tùy chọn, portal, HA |

---

## File / module cần đụng trước (Pha 1)

| Khu vực | File chính | Việc |
|---|---|---|
| Auth bắt buộc | `server/handler.py`, `server/router.py` | Middleware 401 cho GET/POST API |
| Đăng ký / mật khẩu | `server/handlers/auth_handlers.py` | Tắt register, policy mật khẩu |
| Session TTL | `server/services/auth.py` | Kiểm hạn, revoke |
| Lỗi 500 | `server/handler.py` | Không leak `str(e)` |
| Secret | `server/config.json`, `server/config.py`, `.gitignore` | Đưa key ra `.env` |
| Hard-code nội bộ | `server/router.py` (NAME_ALIASES), PIM Vision119 | Cấu hình / tắt mặc định |
| Cookie / header | `server/handler.py`, `Caddyfile` | TTL, CSP, HSTS |
| Backup | `server/services/backup_manager.py` | Xác nhận restore, không lộ path |

---

## Tiêu chí “đủ để bán gói SME”

Chỉ coi là **commercial SME** khi:

1. Người lạ trong LAN **không** đọc được records/PIM khi chưa login.
2. Không tự tạo được tài khoản trên bản production.
3. Admin mời user, có số ghế license.
4. Cài được bằng Docker hoặc service, có HTTPS, backup/restore đã test.
5. Bản giao **không** chứa data, key, alias, connector của công ty gốc.
6. Có EULA + hướng dẫn IT.
7. Nâng cấp không làm mất SQLite / attachments.

Chưa cần SSO/PostgreSQL để bán team 10–40 người; **bắt buộc** có các mục P0.
