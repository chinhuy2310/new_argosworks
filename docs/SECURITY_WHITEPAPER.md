# ARGOS WORKS — Security Whitepaper (tóm tắt cho CISO/CTO)

> Phiên bản 1.0.0. Tài liệu này mô tả kiến trúc bảo mật của bản on-premise.

## 1. Mô hình triển khai & chủ quyền dữ liệu

- **1 khách = 1 instance**, cài trong hạ tầng của khách (máy chủ/VPC/air-gap).
- Toàn bộ dữ liệu nghiệp vụ nằm trong database + `data/` tại máy khách.
- Vendor **không** thu thập telemetry mặc định; không có kết nối ngược về vendor.
- Dữ liệu chỉ rời khỏi hạ tầng khách khi khách **tự cấu hình** AI cloud (Gemini/OpenAI/Claude) hoặc Jira connector. Dùng Ollama + embedding local → không có lưu lượng ra ngoài.

## 2. Xác thực & phiên

| Hạng mục | Cơ chế |
|---|---|
| Mật khẩu | PBKDF2-HMAC-SHA256, 600.000 vòng, salt 16 byte ngẫu nhiên cho từng user |
| Nâng cấp hash | Tự động nâng hash yếu (100k) lên 600k khi đăng nhập thành công |
| Phiên | Token ngẫu nhiên (`secrets`), lưu DB dạng **SHA-256 hash** (không lưu token thô), TTL mặc định 24h |
| Cookie | `HttpOnly`, `SameSite=Lax`, `Secure` khi HTTPS |
| CSRF | HMAC token ràng buộc từng session + double-submit cookie + kiểm tra Origin/Referer |
| Brute force | Khoá 15 phút sau 5 lần sai (theo user **và** theo IP); rate limit 120–180 req/phút/IP |
| Đăng xuất | Xoá session server-side; hỗ trợ đăng xuất mọi thiết bị |
| Tự đăng ký | Tắt mặc định; user mới phải được Admin duyệt (`pending`) |

## 3. Phân quyền (RBAC)

- 4 role: `admin`, `manager`, `member`, `viewer`.
- Kiểm tra **phía server** trên mọi endpoint (`can_view_record`, `can_modify_record`, `can_delete_record`, `can_view_pim_price`).
- Cách ly theo phòng ban: member chỉ thấy việc phòng mình hoặc việc được giao; record `private` giới hạn thêm.
- AI agent dùng **cùng** bộ lọc quyền (`visible_records`, `visible_schedule_events`) trước khi đưa dữ liệu vào prompt (kể cả danh sách việc đang làm và card được tham chiếu trong câu hỏi).
- Semantic search (RAG) áp dụng RBAC theo `doc_type` (`record` / `jira` / `schedule`) trước khi trả kết quả; giá PIM **không** được đưa vào nội dung embedding và luôn được mask theo `can_view_pim_price`.
- Kết quả tìm kiếm ở tab Home chỉ là lớp khám phá: mọi endpoint chi tiết mà kết quả dẫn tới (`/api/issues`, `/api/records/hierarchy`, `/api/jira/attachments`, `/api/attachments`) đều kiểm tra lại `can_view_record` và lọc cả dữ liệu con (subtask/parent/attachment) — chặn IDOR khi người dùng gọi thẳng API.
- CI chạy `scripts/audit_endpoint_rbac.py` để chặn hồi quy: endpoint đọc nhạy cảm không được thiếu kiểm tra session + quyền.

## 4. License & chống gian lận thương mại

- License là payload JSON + **chữ ký Ed25519**, verify bằng public key nhúng trong sản phẩm.
- **Private key không có trong bản giao** (chỉ vendor giữ; công cụ `tools/vendor/license_tool.py` bị loại khỏi bundle).
- Seat/expiry/modules đọc từ **payload đã ký**, không tin cột trong DB → sửa DB không nâng được hạn mức.
- Module không có trong license → API trả 403 (`MODULE_NOT_LICENSED`).
- Hết hạn → **read-only**, không xoá dữ liệu khách.

## 5. Bảo vệ dữ liệu & file

- Mã hoá secret cấu hình (API key, token Jira) bằng AES-256 + HMAC-SHA256 (encrypt-then-MAC, so sánh timing-safe), master key từ `.env` (không nằm trong repo).
- Upload: kiểm tra loại file, giới hạn 25MB, chuẩn hoá tên, chống path traversal; tải file qua endpoint có kiểm tra quyền.
- SSRF: chặn đích nội bộ khi cấu hình URL ngoài (`utils/ssrf.py`).
- Backup `.tar.gz` được kiểm tra path traversal/symlink/tar-bomb trước khi restore; restore luôn tạo safety snapshot.

## 6. Nhật ký kiểm toán

- Bảng `audit_logs` ghi: thời gian, user, phòng, IP, hành động, đối tượng, chi tiết JSON.
- Ghi các sự kiện: login/logout/thất bại, tạo-sửa-xoá record, đổi quyền, backup/restore, đổi license, export audit.
- Mật khẩu/token/API key bị **che** trước khi ghi (`******`).
- Xuất CSV/JSON theo khoảng ngày; chống CSV formula injection.

## 7. Bảo vệ tầng HTTP

- Header bảo mật: `X-Content-Type-Options`, `X-Frame-Options`/CSP, `Referrer-Policy`, HSTS (khi HTTPS), CORS whitelist (không bao giờ `*` với credentials).
- `Server` header không lộ phiên bản; `/api/health` không lộ cấu hình.
- Không trả stack trace ra client; lỗi 500 được log nội bộ.
- Giới hạn kích thước body, timeout, rate limit theo IP; tin cậy `X-Forwarded-For` **chỉ** từ proxy trong `TRUSTED_PROXIES`.

## 8. Supply chain & vận hành

- Dependency pin trong `requirements.txt` / `requirements.lock`.
- CI: `pip-audit`, Bandit, Trivy (image), SBOM CycloneDX, `compileall`, `node --check`.
- Docker image chạy user không phải root; healthcheck tích hợp.
- Backup/restore có test tự động (`tests/test_backup_restore.py`).

## 9. Giới hạn đã biết (công bố minh bạch)

1. **SQLite** phù hợp ≤ 20–30 user đồng thời; trên ngưỡng phải PostgreSQL.
2. **MFA/TOTP, LDAP, SAML/SCIM** chưa có trong 1.0.0 (SSO OIDC có module nền tảng).
3. **AI cloud** nhận nội dung prompt — cần opt-in bằng văn bản nếu khách dùng.
4. Chưa có **pentest bên thứ ba** cho 1.0.0; khuyến nghị thực hiện trước khi triển khai tập đoàn.
5. Audit log lưu trong cùng DB: Admin có quyền DB có thể sửa — nếu cần chống sửa tuyệt đối, cần đẩy log ra hệ thống ngoài (SIEM) ở phiên bản sau.
