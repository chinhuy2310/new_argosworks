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

### 5.2b Bản dùng thử (trial) có thời hạn

License trial chứa `term_days` (ví dụ 60) trong payload đã ký. Hạn dùng **được tính từ lần kích hoạt đầu tiên**, không phải từ ngày phát hành hay ngày cài:

- Hạn hiệu lực = `ngày kích hoạt đầu tiên + term_days`. Key trial **không cần** ngày hết hạn tuyệt đối; nếu vendor có ký kèm `expiry` thì đó là **hạn cứng** (không bao giờ vượt qua).
- Kích hoạt lại **cùng key** (nâng cấp phiên bản, restore DB) **không** làm mới thời gian thử.
- Cột `license_info.activated_at` lưu mốc kích hoạt đầu tiên; sửa giá trị này trong DB sẽ bị vô hiệu (hệ thống kẹp về khoảng `[iat, hôm nay]`).
- **Chống lùi đồng hồ**: hệ thống lưu mốc thời gian lớn nhất từng thấy (`license_info.last_seen_ts`, cập nhật tối đa 1 giờ/lần, không bao giờ giảm). Nếu đồng hồ hệ thống bị chỉnh về trước mốc đó (dung sai 5 phút cho NTP), mọi phép tính trial dùng **mốc cao nhất** thay vì giờ hiện tại → thời gian thử **không** được kéo dài, và UI hiện cảnh báo `clock_rollback_detected`.
- Hết thời gian thử → **read-only** giống license hết hạn; kích hoạt lại key trial đã hết hạn bị từ chối (`체험 기간(60일)이 종료되었습니다`).
- UI hiển thị badge `체험판 (D-xx)`, dòng **체험 기간 60일 (활성화 YYYY-MM-DD)** và **체험 만료일**.
- Giới hạn đã biết: xoá toàn bộ thư mục `data/` (DB + mốc neo + mốc thời gian) rồi kích hoạt lại sẽ bắt đầu trial mới; muốn chặn tuyệt đối cần license server online hoặc key gắn định danh máy.

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

### 8.1 Console khởi động, mã thoát và log

Bản đóng gói (`ArgosWorks.exe`) in một banner **100% tiếng Anh** ngay sau khi cổng HTTP đã bind thành công
(`[READY]`). Mọi giá trị trong banner (đường dẫn dữ liệu, IP LAN, cổng, đường dẫn CA) được tính **lúc chạy**
nên sang máy khác / thư mục cài khác / user Windows khác vẫn đúng.

- **Mã thoát**: `0` = đang chạy **hoặc** tái dùng instance đang chạy; `1` = lỗi khởi động; `2` = `config.json` sai.
- **Instance trùng**: mỗi `data/` chỉ do một tiến trình phục vụ (`data/.server.lock`). Chạy lần 2 sẽ mở lại
  phiên đang chạy thay vì khởi động server thứ hai (tránh 2 scheduler backup/vector cùng ghi DB).
- **Log**: mọi lần khởi động ghi vào `logs/startup.log`; log Caddy ở `logs/caddy.log`. Khi cửa sổ console
  đóng ngay, đọc 2 file này để biết nguyên nhân.
- **Lỗi hay gặp**:

  | Thông báo | Nguyên nhân | Cách xử lý |
  |---|---|---|
  | `Port <n> is already in use by another process (PID ...)` | Ứng dụng khác giữ cổng | Đóng ứng dụng đó, hoặc đổi `server.port` |
  | `Windows rejected the bind on ... (reserved range)` | Hyper-V/WSL/Docker giữ dải cổng | `netsh int ipv4 show excludedportrange protocol=tcp` rồi chọn cổng khác |
  | `The configured host ... is not assigned to this computer` | `server.host` là IP không thuộc máy | Đổi thành `0.0.0.0` hoặc IP trong `ipconfig` |
  | `The ARGOS WORKS data directory is already in use` | Instance cũ treo chưa thoát | Đóng tiến trình/PID được in ra rồi chạy lại |
  | `Caddy did not open port 8443 within 15s` | Caddy lỗi cấu hình/chứng chỉ | Xem `logs/caddy.log`; tạm thời dùng URL HTTP |

- **HTTPS trên LAN (chứng chỉ nội bộ)**: Caddy dùng CA nội bộ lưu tại `data/caddy/pki/authorities/local/root.crt`
  (theo từng bản cài, không theo từng user). Để máy trạm không báo lỗi chứng chỉ, mở
  `http://<IP-máy-chủ>:8080/argos-root-ca.crt` trên máy trạm và cài làm **Trusted Root CA** (quyền Administrator).
  Chỉ làm trên máy công ty; nếu không, dùng URL HTTP. Tuyệt đối **không** sao chép `root.key` ra ngoài.
- Có thể tắt tự mở trình duyệt bằng `ARGOS_NO_BROWSER=1`; giữ cửa sổ console khi chạy tự động bằng `ARGOS_NO_PAUSE=1`.

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

### 9.1 Debugging và Log tham số SQL

- Mặc định hệ thống **không bao giờ** ghi giá trị tham số SQL vào log nhằm chống lộ dữ liệu nhạy cảm (mật khẩu, salt, token, session).
- Biến môi trường \ARGOS_LOG_SQL_PARAMS=1\: **CHỈ DÙNG TẠM THỜI KHI HỖ TRỢ KỸ THUẬT ĐỂ ĐIỀU TRA SỰ CỐ**. Tuyệt đối **KHÔNG BẬT** trên môi trường production vì có thể ghi nhận dữ liệu nhạy cảm vào log file và hệ thống SIEM.

## 10. Nhật ký kiểm toán (Audit)

- **Settings → 감사 로그 (Audit)**: lọc theo loại sự kiện, user, khoảng ngày.
- Xuất **CSV/JSON** để nộp kiểm toán (UTF-8, mở trực tiếp bằng Excel).
- Sự kiện được ghi: đăng nhập/thất bại, tạo/sửa/xoá record, đổi role, backup/restore, đổi license, export audit.
- Audit **không** ghi mật khẩu, token hay API key.

## 11. Jira: ánh xạ người dùng (alias 2 chiều)

Tên người trên ARGOS và Jira thường khác nhau (ví dụ ARGOS `John Doe` ↔ Jira `johnd`,
hoặc ARGOS `김철수` ↔ Jira `chulsoo.kim@company.com`). Khai báo một lần, dùng cho **cả hai chiều**:

**Settings → API 및 외부 연동 → Jira → 사용자 별칭 (User Aliases, JSON)**

```json
{
  "홍길동": "gildong.hong@company.com",
  "김철수": "chulsoo.kim@company.com",
  "John Doe": "johnd"
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
