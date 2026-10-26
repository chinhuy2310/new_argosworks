# ARGOS WORKS — Hướng dẫn Quản trị (Admin Guide)

> Đối tượng: IT Admin / quản trị viên hệ thống của khách hàng.
> Phiên bản áp dụng: **1.0.0** — mô hình **on-premise, 1 khách = 1 instance**.

---

## 1. Kiến trúc tóm tắt

| Thành phần | Chi tiết |
|---|---|
| Backend | Python 3.10+ (stdlib HTTP + WSGI), chạy `waitress` hoặc `gunicorn` phía sau reverse proxy |
| Database | PostgreSQL 14+ (mặc định trong Docker Compose) hoặc SQLite (nhóm ≤ 20–30 người) |
| Reverse proxy | Caddy (tự động HTTPS) hoặc IIS/Nginx của khách |
| Dữ liệu | `data/` (DB, attachments, backups, vector store) — **không được xoá khi nâng cấp** |
| Cấu hình | `.env` (secrets) + `server/config.json` (không chứa secret) |

## 2. Yêu cầu hạ tầng tối thiểu

| Quy mô | CPU | RAM | Disk | DB |
|---|---|---|---|---|
| ≤ 20 user | 2 vCPU | 4 GB | 40 GB SSD | SQLite |
| 20–50 user | 4 vCPU | 8 GB | 100 GB SSD | PostgreSQL 14+ |
| > 50 user | 8 vCPU | 16 GB | 200 GB SSD | PostgreSQL 14+ (backup offsite) |

Mở firewall: `443` (HTTPS) cho người dùng; `8080` **chỉ** cho reverse proxy nội bộ.

## 3. Cài đặt lần đầu

### 3.1 Docker Compose (khuyến nghị)

```bash
cp .env.example .env
# Sinh khoá bắt buộc:
#   ARGOS_MASTER_KEY: openssl rand -hex 32
#   POSTGRES_PASSWORD: openssl rand -hex 16
#   DOMAIN: tên miền nội bộ (ví dụ argos.congty.local)
docker compose up -d --build
docker compose ps          # argos-works, argos-proxy, argos-postgres phải "Up"
```

### 3.2 Cài trực tiếp (không Docker)

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
python -m waitress --listen=0.0.0.0:8080 server.wsgi:application
```

Chạy như service: xem `deploy/argos-works.service` (Linux) hoặc
`deploy/install_windows_service.ps1` (Windows).

### 3.3 Setup Wizard (bắt buộc một lần)

Mở `https://<domain>/setup.html` và thực hiện 3 bước:

1. Kiểm tra license (dán key `AGY-...` do nhà cung cấp gửi).
2. Tạo tài khoản **Admin đầu tiên** (mật khẩu ≥ 8 ký tự).
3. Khai báo công ty + danh sách phòng ban.

> Sau bước này, tự đăng ký công khai bị tắt (`ALLOW_PUBLIC_REGISTER=false`).

## 4. Quản lý người dùng và phân quyền

| Role | Quyền |
|---|---|
| `admin` | Toàn hệ thống: user, backup, license, settings, audit |
| `manager` | Toàn bộ công việc của phòng mình, duyệt chuyển trạng thái |
| `member` | Tạo/sửa việc được giao; không xem giá PIM |
| `viewer` | Chỉ đọc, không tạo/sửa/xoá |

- Tạo user: **Settings → 사용자 & 권한 (RBAC) → ➕ 새 사용자 등록**.
- User mới đăng ký công khai (nếu bật) sẽ ở trạng thái `pending` và phải được Admin duyệt.
- Khoá user: đặt `disabled = 1` — **không** xoá để giữ lịch sử công việc.
- Giới hạn ghế: khi số user active ≥ `max_seats`, tạo/duyệt user bị chặn (HTTP 403).

## 5. License

### 5.1 Trạng thái

**Settings → 🔑 라이선스 (License)**: hiển thị khách hàng, ghế đã dùng/tổng, ngày hết hạn (+ cảnh báo trước 30 ngày), module được cấp và kết quả kiểm tra chữ ký Ed25519.

### 5.2 Kích hoạt / gia hạn

1. Nhận file `.lic` hoặc chuỗi key `AGY-...` từ nhà cung cấp.
2. Dán vào ô **라이선스 활성화 / 갱신** → **활성화**.
3. Hoặc offline: `python scripts/apply_license.py duong/dan/cong-ty.lic --db data/argos.db` rồi restart service.

### 5.3 Hết hạn

Hệ thống chuyển **read-only**: không ghi/sửa/xoá mới, **dữ liệu cũ vẫn đọc được**. Gia hạn → ghi bình thường trở lại.

### 5.4 Module

License có thể chỉ gồm một số module (`canvas`, `pim`, `jira`, `rag`, `schedule`, `audit`). Module không có trong license bị **chặn ở API (HTTP 403, mã `MODULE_NOT_LICENSED`)** — không thể vượt bằng cách gọi trực tiếp endpoint.

## 6. Backup & Restore

- **Tự động**: scheduler chạy khi khởi động qua WSGI (`wsgi.py` — Docker/systemd/waitress), kiểm tra mỗi giờ và backup khi đã qua `backup.interval_hours` (mặc định 24h) + retention (`retention_days`, `retention_count`).
  > Nếu chạy dev bằng `python server/main.py`, scheduler không được bật → phải backup thủ công.
- **Thủ công**: Settings → 보안 & DB 백업 → **백업 생성**.
- **Vị trí**: `BACKUP_DIR` trong `.env` (khuyến nghị trỏ NAS/ổ ngoài).
- **Restore**: chọn file → 복원. Hệ thống **tự tạo safety snapshot** trước khi ghi đè.
- **Diễn tập định kỳ (bắt buộc)**: mỗi quý restore 1 file sang máy staging và đối chiếu số record.
- Backup gồm: database + `data/attachments`. Không gồm `.env` → **phải backup `.env` riêng**.

## 7. Nâng cấp phiên bản

1. Backup DB + `.env` + `data/`.
2. Dừng service.
3. Thay thế code (giữ nguyên `data/`, `.env`, `server/config.json`).
4. Chạy migration: `python -c "import sys; sys.path.insert(0,'server'); import db; db.init_db()"`.
5. Khởi động lại, kiểm tra `/api/health` và `/api/version`.
6. Rollback = restore backup + code phiên bản trước (xem `CHANGELOG.md`).

## 8. Kiểm tra sức khoẻ hệ thống

```bash
curl -f https://<domain>/api/health     # {"ok":true,"database":{"status":"connected"}}
curl    https://<domain>/api/version    # {"version":"1.0.0"}
```

`/api/health` trả **503** khi DB không kết nối được → dùng cho monitoring/load balancer.

## 9. Xử lý sự cố thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| 403 `유효한 라이선스가 없습니다` | License chưa kích hoạt / sai chữ ký | Kích hoạt lại key do nhà cung cấp cấp |
| Hệ thống chỉ đọc | License hết hạn | Gia hạn license |
| 403 `MODULE_NOT_LICENSED` | Module không có trong license | Yêu cầu nâng gói |
| Không đăng nhập được sau setup | Sai mật khẩu admin | Admin khác reset; nếu mất hết: restore backup |
| Upload file lỗi | Vượt `max_upload_mb` (25MB) | Tăng trong `server/config.json` |
| AI không trả lời | Thiếu API key hoặc Ollama offline | Settings → API 및 외부 연동 → 연결 테스트 |
| Không đăng nhập được bằng tài khoản công ty (SSO) | 1.0.0 **chưa hỗ trợ** SSO/LDAP — dùng tài khoản nội bộ do Admin tạo | Theo dõi `CHANGELOG.md` cho bản có OIDC |

## 10. Nhật ký kiểm toán (Audit)

- **Settings → 감사 로그 (Audit)**: lọc theo loại sự kiện, user, khoảng ngày.
- Xuất **CSV/JSON** để nộp kiểm toán (UTF-8, mở trực tiếp bằng Excel).
- Sự kiện được ghi: đăng nhập/thất bại, tạo/sửa/xoá record, đổi role, backup/restore, đổi license, export audit.
- Audit **không** ghi mật khẩu, token hay API key.

## 11. Jira: ánh xạ người dùng (alias 2 chiều)

Tên người trên ARGOS và Jira thường khác nhau (ví dụ ARGOS `Đồng Chí Huy` ↔ Jira `Uy`,
hoặc ARGOS `김철수` ↔ Jira `chulsoo.kim@company.com`). Khai báo một lần, dùng cho **cả hai chiều**:

**Settings → API 및 외부 연동 → Jira → 사용자 별칭 (User Aliases, JSON)**

```json
{
  "Đồng Chí Huy": "Uy",
  "김철수": "chulsoo.kim@company.com",
  "Nguyễn Văn A": "a.nguyen@congty.com"
}
```

| Chiều | Tác dụng |
|---|---|
| **Local → Jira** | Khi tạo/push card, hệ thống tìm `accountId` bằng giá trị alias → gán đúng **assignee + reporter** bên Jira |
| **Jira → Local** | Khi sync issue về, assignee được đổi thành **tên local** → thẻ hiện đúng trong **“Việc của tôi”**, lịch cá nhân, và phân quyền theo phòng |

Quy tắc:
- Không phân biệt hoa/thường; **bỏ chức danh** khi so sánh (`김철수 대리` khớp `김철수`).
- Ưu tiên **email** nếu Jira trả về `emailAddress` (chính xác nhất), sau đó mới tới tên/alias.
- Thẻ Jira của project **chưa map phòng** vẫn được nhận diện theo alias (không còn bị “mồ côi”).
- Lưu Settings là cache Jira được nạp lại; nên bấm **⟳ Jira 동기화** để áp alias cho dữ liệu cũ.
- Tên hiển thị gốc bên Jira vẫn được giữ ở `jira.displayAssignee` (dùng khi đối chiếu).

---

## 12. Checklist bàn giao cho IT khách hàng

- [ ] `.env` có `ARGOS_MASTER_KEY` riêng (không dùng giá trị mẫu), `ALLOW_PUBLIC_REGISTER=false`
- [ ] HTTPS hoạt động, HTTP redirect 301 → HTTPS
- [ ] Admin đầu tiên đã tạo, mật khẩu mạnh, đã đổi mặc định
- [ ] License hợp lệ, đúng số ghế, còn hạn
- [ ] Backup tự động bật + đã restore thử thành công
- [ ] Service tự khởi động lại sau reboot
- [ ] Monitoring gọi `/api/health` mỗi 30–60s
- [ ] Đã bàn giao: Admin Guide, User Guide, EULA, SLA, đầu mối hỗ trợ
