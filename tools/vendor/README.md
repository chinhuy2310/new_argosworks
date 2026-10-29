# Vendor License Tools (Nội bộ Vendor)

Thư mục này chứa các công cụ nội bộ của Vendor dùng để tạo, ký số và quản lý License bản quyền phần mềm ARGOS WORKS.

> **CẢNH BÁO BẢO MẬT:**
> - Toàn bộ thư mục này và khóa bí mật (`license_signing_key.hex`) **KHÔNG BAO GIỜ** được đóng gói gửi cho khách hàng.
> - Script `scripts/build_release.py` đã cấu hình loại bỏ toàn bộ thư mục `tools/vendor` khỏi bản cài đặt release.

---

## 1. Ứng dụng Desktop có Giao diện đồ họa (GUI)
Để mở ứng dụng quản lý License trực quan trên Windows:
- **Cách nhanh nhất:** Nhấp đúp chuột vào file `run_license_manager.bat` ở thư mục gốc.
- **Hoặc chạy lệnh:**
  ```bash
  python tools/vendor/license_gui.py
  ```

### Các tính năng trên giao diện:
1. **Phát hành License:**
   - Hỗ trợ tạo License **Thương mại** (chọn ngày hết hạn cố định) hoặc **Dùng thử (Trial)** (nhập số ngày dùng thử, thời gian chỉ bắt đầu đếm từ lần kích hoạt đầu tiên trên máy khách).
   - Tùy chọn bật/tắt từng phân hệ chức năng: `Canvas`, `PIM`, `Jira`, `RAG`, `Schedule`, `Audit`.
   - Tự động xuất file `.lic` vào thư mục `licenses/` và ghi nhật ký vào `issued_licenses.csv`.
2. **Kiểm tra File .lic (Inspect):**
   - Kéo-thả hoặc chọn file `.lic` để kiểm tra tính hợp lệ và xem chi tiết thông tin đã cấp.
3. **Lịch sử cấp phép (History):**
   - Xem và tìm kiếm danh sách các khách hàng đã được cấp license.

---

## 2. Công cụ dòng lệnh (CLI Tool)
Nếu muốn sử dụng bằng lệnh trong terminal:
```bash
# Tạo license thương mại
python tools/vendor/license_tool.py issue --customer "Ten Khach Hang" --seats 50 --expiry 2027-12-31 --modules canvas,pim,jira,rag,schedule,audit --out licenses/out.lic

# Tạo license trial
python tools/vendor/license_tool.py issue --trial --days 60 --customer "Ten Khach Hang" --seats 50 --modules canvas,pim,jira,rag,schedule,audit --out licenses/trial.lic

# Kiểm tra file .lic
python tools/vendor/license_tool.py inspect licenses/trial.lic
```
