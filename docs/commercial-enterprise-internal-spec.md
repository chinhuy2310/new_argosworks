# 🏢 ARGOS WORKS — Commercial Enterprise Internal-Use Software Specification

> **Phiên bản:** 1.0.0  
> **Mục tiêu định vị:** Commercial-Grade Internal Operations & Handover Portal  
> **Đối tượng phục vụ:** Nội bộ doanh nghiệp, các phòng ban R&D, Quản lý dự án, Kỹ sư, Ban Giám đốc và các chi nhánh / nhà máy.

---

## 🎯 1. ĐỊNH NGHĨA "COMMERCIAL ENTERPRISE INTERNAL SOFTWARE"

Một phần mềm nội bộ đạt chuẩn **Commercial-Grade (Đẳng cấp thương mại)** khác biệt hoàn toàn với một "công cụ viết tạm":
- **Tính Bền vững (High Availability):** Vận hành ổn định 24/7, không có lỗi dừng hệ thống đột ngột.
- **Tính Toàn vẹn Dữ liệu (Zero Data Loss):** Không bao giờ xảy ra tình trạng ghi đè hoặc mất dữ liệu khi nhiều người truy cập đồng thời.
- **Bảo mật Nội bộ (Zero Trust & Least Privilege):** Phân quyền chặt chẽ giữa các phòng ban, ngăn ngừa rò rỉ giá vốn, bí mật thiết kế R&D và thông tin nhân sự.
- **Tính Độc lập (Self-Contained / Air-Gapped Ready):** Chạy độc lập trong mạng LAN/VPN của công ty, không phụ thuộc vào các dịch vụ công cộng không an toàn (như link Google Sheets public).
- **Trải nghiệm Xuất sắc (Enterprise UX):** Tốc độ phản hồi cực nhanh, hỗ trợ đa ngôn ngữ (Anh/Hàn), xuất báo cáo chuẩn phôi của công ty.

```mermaid
flowchart TD
    subgraph "Clients"
        E["Engineers / Staff"]
        M["Managers / PMs"]
        D["Directors / Executives"]
    end

    subgraph "Security Perimeter (LAN / VPN)"
        CADDY["Caddy Reverse Proxy<br/>(Internal TLS / HSTS / CSP)"]
        
        subgraph "Application Core"
            APP["ARGOS Core Engine<br/>(Python stdlib HTTP + WSGI)"]
            AI["AI ReAct Assistant<br/>(RAG + Function Calling)"]
            SEC["Enterprise Security<br/>(OpenSSL AES + Rate Limit + RBAC)"]
        end
        
        subgraph "Data Storage"
            PG[("PostgreSQL 14+ / SQLite WAL<br/>(dữ liệu tại chỗ; secret mã hoá)")]
            VEC[("Vector Semantic DB<br/>(Knowledge RAG)")]
            FS[("Secure Attachments<br/>(Non-root Storage)")]
        end
    end

    subgraph "External Connectors"
        JIRA["Atlassian Jira Cloud / DC<br/>(Encrypted Token)"]
        LLM["AI Providers<br/>(Gemini / OpenAI / Claude)"]
    end

    E --> CADDY
    M --> CADDY
    D --> CADDY
    CADDY --> APP
    APP --> SEC
    APP --> AI
    SEC --> PG
    AI --> VEC
    APP --> FS
    APP --> JIRA
    AI --> LLM
```

---

## 🛡️ 2. MA TRẬN PHÂN QUYỀN NỘI BỘ (ENTERPRISE RBAC)

Hệ thống thiết lập 4 cấp độ quyền hạn phân tầng, bảo vệ chặt chẽ tài sản trí tuệ và dữ liệu tài chính:

| Cấp Quyền | Đối Tượng | Quyền Hạn Chi Tiết | Giới Hạn Bảo Mật |
|---|---|---|---|
| **`admin`** (Quản trị viên) | IT Admin, Giám đốc R&D | Toàn quyền cấu hình hệ thống, quản lý tài khoản, xem toàn bộ audit log, tải mẫu báo cáo, cấu hình Jira & AI, quản lý license/backup. | Khoá 15 phút sau 5 lần đăng nhập sai (theo user và theo IP). MFA chưa có trong 1.0.0. |
| **`manager`** (Trưởng phòng/PM) | Trưởng bộ phận, Quản đốc | Xem toàn bộ task trong phòng ban, duyệt tiến độ, xuất báo cáo tuần (Excel), xem giá sản phẩm PIM (nếu thuộc phòng Kinh doanh/Điều hành). | Không được can thiệp vào cài đặt API hệ thống của IT. |
| **`member`** (Kỹ sư/Nhân viên) | Kỹ sư R&D, Lập trình viên, Tester | Tạo task mới, cập nhật tiến độ công việc của mình, chat với AI trợ lý, tra cứu thông số kỹ thuật PIM. | **Bị ẩn giá bán/giá vốn PIM**; không thể xóa task của người khác. |
| **`viewer`** (Khách/Thực tập sinh) | Đối tác, Nhân viên thử việc | Chỉ đọc (Read-only) các tài liệu và danh mục sản phẩm được công khai. | Chặn toàn bộ thao tác thêm/sửa/xóa hoặc gọi tool AI thay đổi dữ liệu. |

---

## ⚙️ 3. TIÊU CHUẨN KỸ THUẬT VÀ HẠ TẦNG VẬN HÀNH

### 3.1 Cơ Sở Dữ Liệu: 2 Tùy Chọn Linh Hoạt (Dual-Database Strategy)
1. **Chế độ Single-Node / Nhánh nhỏ (< 50 nhân viên):**
   - Sử dụng **SQLite với chế độ WAL (Write-Ahead Logging)** và `busy_timeout = 5000`.
   - Ưu điểm: Zero-setup, cực nhẹ, toàn bộ dữ liệu gói gọn trong 1 file `data/argos.db`, dễ dàng copy backup.
2. **Chế độ Enterprise Scale / Tập đoàn (> 50 nhân viên đồng thời):**
   - Sử dụng **PostgreSQL 16 Enterprise** (đã có sẵn file `schema.postgres.sql` và container trong `docker-compose.yml`).
   - Kết nối qua Connection Pool (`asyncpg` / `psycopg3`), hỗ trợ hàng trăm kỹ sư cập nhật tiến độ cùng một giây mà không bao giờ bị khóa bảng (Row-level Locking).

### 3.2 Tách Rời Hoàn Toàn Các Phụ Thuộc Nguy Hiểm
- **Google Sheets:** Đã bị ngắt kết nối hoàn toàn. Mọi dữ liệu báo cáo được tính toán trực tiếp từ cơ sở dữ liệu nội bộ và Jira.
- **External Comments DB (`choivis-v2`):** Không còn đường dẫn cứng sang máy khác; mã nguồn hoàn toàn độc lập, có thể mang đi cài đặt ở bất kỳ đâu.
- **Hardcoded Person Aliases:** Toàn bộ danh sách nhân sự được nạp tự động từ cơ sở dữ liệu `users`.

### 3.3 Hệ Thống Báo Cáo Song Ngữ Chuẩn Doanh Nghiệp (EN/KO)
Báo cáo tuần tự động tổng hợp công việc từ Jira và Local DB, xuất ra định dạng Excel `.xlsx` 12 cột chuẩn:
- **Tiêu đề song ngữ:** Tùy chọn xuất ra tiếng Anh (`lang=en`) cho các dự án quốc tế hoặc tiếng Hàn (`lang=ko`) cho ban giám đốc.
- **Phôi báo cáo riêng (White-label Templates):** Hỗ trợ nạp file mẫu Excel riêng của công ty với Logo và Form chuẩn thông qua API `POST /api/reports/template`.

---

## 🚀 4. QUY TRÌNH TRIỂN KHAI PRODUCTION CHUẨN ENTERPRISE

### Bước 1: Chuẩn Bị Môi Trường
Khởi tạo file cấu hình từ file mẫu:
```bash
cp .env.example .env
```
Cấu hình các thông số bảo mật bắt buộc trong `.env`:
```ini
# Khoá master mã hoá secret cấu hình (API key Jira/AI) — BẮT BUỘC, 64 ký tự hex
# sinh bằng: openssl rand -hex 32
ARGOS_MASTER_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

# Mật khẩu PostgreSQL (nếu dùng PostgreSQL)
DATABASE_URL=postgresql://argos_admin:YOUR_STRONG_PASSWORD_HERE@postgres:5432/argos_works

# Bắt buộc tắt tự đăng ký trên production
ALLOW_PUBLIC_REGISTER=false
SESSION_TTL_HOURS=24

# Khoá AI & Jira của công ty (có thể nhập sau trong Settings)
GEMINI_API_KEY=
JIRA_BASE_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=

# Domain nội bộ
DOMAIN=argos.internal.company.com
```

> **Lưu ý:** license được ký bằng khoá Ed25519 **chỉ vendor nắm giữ**. Bản của khách
> không có private key và không cần khai báo khoá ký trong `.env`; license được nhập ở
> Setup Wizard hoặc **Settings → 🔑 License**.

### Bước 2: Khởi Chạy Hệ Thống Qua Docker
Hệ thống đã được đóng gói container tối ưu (chạy user `appuser` non-root, có sẵn Caddy auto-SSL và giới hạn 2GB RAM):
```bash
docker compose up -d --build
```

### Bước 3: Kiểm Tra Tình Trạng Hệ Thống (Health Check)
Truy cập endpoint kiểm tra trạng thái hoạt động:
```bash
curl -f https://argos.internal.company.com/api/health
# Kết quả mong đợi (HTTP 200):
# {"ok":true,"status":"healthy","time":"...","database":{"status":"connected"}}
# Trả HTTP 503 nếu không kết nối được database.
```

---

## 💾 5. KẾ HOẠCH SAO LƯU & KHÔI PHỤC (BACKUP & DISASTER RECOVERY)

Để đảm bảo dữ liệu nội bộ không bao giờ bị mất, thiết lập lịch backup tự động:

1. **Với SQLite:**
   Backup Manager dùng SQLite Online Backup API (an toàn cả khi đang ở WAL mode), kiểm tra
   `PRAGMA integrity_check`, đóng gói `.tar.gz` gồm DB + `data/attachments`, kèm SHA-256.
   Tên file dạng `argos_backup_YYYYMMDD_HHMMSS_manual.tar.gz` (+ `backups_manifest.json`).
2. **Với PostgreSQL (Khuyến nghị cho Production):**
   Backup Manager gọi `pg_dump -Fc` (custom format) — có thể chạy tự động theo
   `backup.interval_hours` hoặc thủ công trong Settings.
3. **Restore:** luôn tạo snapshot an toàn `argos_safety_before_restore_*.tar.gz` trước khi ghi đè,
   sau đó chạy lại migration `init_db()` để đồng bộ schema. Quy trình này có test tự động
   (`tests/test_backup_restore.py`).
4. **Lưu trữ Off-site:**
   Trỏ `BACKUP_DIR` sang NAS/ổ ngoài và sao chép định kỳ — backup chỉ nằm cùng ổ đĩa không được coi là backup.

---

## ✅ 6. BỘ KIỂM THỬ TỰ ĐỘNG (QUALITY ASSURANCE)

Mỗi lần cập nhật code, CI chạy **hai** bộ kiểm thử (xem `.github/workflows/ci.yml`):

```bash
# 1) Bộ pytest (unit / integration / e2e) + coverage
python -m pytest -q --cov=server --cov-report=term-missing

# 2) Bộ unittest cũ (audit / RBAC / WSGI / PostgreSQL smoke)
python -m unittest discover -s tests -v
```

Các cổng chất lượng hiện có:
- Unit/Integration/E2E: auth, session, RBAC theo phòng ban, license entitlements,
  backup→restore round-trip, WSGI/CORS, audit export, migration SQLite→PostgreSQL.
- `python -m compileall` cho toàn bộ Python và `node --check` cho JS.
- SAST/Dependency: Bandit, pip-audit, Trivy (Docker image), SBOM CycloneDX.
- Hành vi bảo mật được kiểm chứng bằng test: license giả/không ký bị từ chối, sửa DB
  không nâng được ghế/hạn, module thiếu bị 403, rate-limit và lockout hoạt động.

> Không có hệ thống nào "không thể bypass" tuyệt đối. Các test trên chứng minh những
> đường tấn công đã biết đang bị chặn; pentest độc lập vẫn được khuyến nghị trước khi
> triển khai cho tập đoàn.

---

> [!IMPORTANT]
> **Kết luận:** ARGOS WORKS 1.0.0 đáp ứng mô hình **phần mềm nội bộ on-premise cấp thương mại**
> cho nhóm 10–50 người: có RBAC, audit, backup/restore đã kiểm thử, license ký số và CI gate.
> Các giới hạn còn lại (MFA/LDAP, i18n tiếng Việt, pentest độc lập, HA PostgreSQL) được liệt kê
> minh bạch trong `docs/SECURITY_WHITEPAPER.md` mục 9 và `CHANGELOG.md`.
