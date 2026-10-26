# ARGOS WORKS — Hướng dẫn Người dùng (User Guide)

> Dành cho nhân viên sử dụng hằng ngày. Bản 1.0.0.

---

## 1. Đăng nhập

1. Mở `https://<domain>/login.html`.
2. Nhập **ID (username)**, email hoặc tên + mật khẩu.
3. Sai 5 lần → tài khoản bị tạm khoá 15 phút (liên hệ Admin nếu cần mở).

> Tự đăng ký mặc định **bị tắt**. Tài khoản do Admin tạo hoặc duyệt.

## 2. Màn hình chính

| Tab | Dùng để |
|---|---|
| 🏠 홈 | Hỏi nhanh trợ lý AI |
| 📊 대시보드 | Xem công việc theo phòng ban / người phụ trách / cây phân cấp |
| 💬 AI 채팅 | Hỏi đáp trên dữ liệu nội bộ (RAG), tạo việc bằng hội thoại |
| 📅 캘린더 | Lịch cá nhân (nghỉ phép, công tác, họp) + hạn công việc |
| 📦 PIM | Tra cứu sản phẩm, thông số kỹ thuật, tài liệu |
| 🔌 외부 연동 / Settings | (Admin) cấu hình AI, Jira, backup, license |

## 3. Công việc (Card)

**Tạo việc**: nút tạo mới → nhập tiêu đề, phòng ban, người phụ trách, hạn chót, mô tả → lưu.

**Cập nhật**: mở card → **✏️ 수정** (tiêu đề, người phụ trách, người tham gia, ngày, nội dung, mức ưu tiên).

**Trạng thái**: `예정` (chờ) → `진행` (đang làm) → `검토` (chờ duyệt) → `완료` (xong).
Chỉ `manager`/`admin` được duyệt sang `완료`.

**Cây phân cấp**: đặt `parentKey` để gắn việc con vào việc cha (ví dụ `DEV-102`).

**Xung đột dữ liệu**: nếu người khác vừa sửa, hệ thống báo *버전 충돌* → bấm **최신 데이터 불러오기** rồi sửa lại (không bị ghi đè âm thầm).

## 4. Ghi chú riêng tư (Private)

Hệ thống hỗ trợ cờ `is_private` ở tầng dữ liệu: card private chỉ người tạo, người phụ trách,
trưởng phòng và Admin đọc được; card **không** xuất hiện trong tìm kiếm/dashboard của phòng khác
và AI cũng không trả về cho người không có quyền.

> ⚠️ Trong 1.0.0 **chưa có nút bật/tắt Private trên giao diện** — cờ này được đặt qua API/import
> dữ liệu hoặc bởi Admin. Tính năng UI đang nằm trong roadmap.

## 5. AI Assistant

- Hỏi bằng tiếng Hàn / Anh / Việt — trợ lý trả lời cùng ngôn ngữ.
- Có thể hỏi: *"Tuần này tôi có việc gì?"*, *"Tóm tắt DEV-102"*, *"Thông số sản phẩm ABC"*.
- Trợ lý **chỉ** trả về dữ liệu bạn được xem (lọc theo phòng ban/quyền).
- Hệ thống có thể gợi ý hành động (tạo việc, đổi trạng thái) — bạn phải xác nhận mới thực thi.

## 6. Lịch

- Thêm nghỉ phép / công tác / họp: chọn ngày → loại sự kiện → lưu.
- Sự kiện chờ duyệt hiện màu vàng; quản lý duyệt/từ chối kèm lý do.
- Hạn công việc và deadline Jira tự hiển thị trên lịch.

## 7. PIM (thông tin sản phẩm)

- Tìm theo mã model, tên, nhóm sản phẩm.
- Xem thông số kỹ thuật, tài liệu firmware, thông tin mua sắm.
- **Giá và giá vốn bị ẩn** với `member`/`viewer`; chỉ Admin và phòng kinh doanh thấy.

## 8. Đính kèm file

Kéo–thả hoặc chọn file trong card (tối đa 25MB/file). Ảnh được nén tự động; mọi file được kiểm tra loại và chống path traversal.

## 9. Thông báo

Chuông 🔔 góc trên: có việc mới được giao, chuyển trạng thái, duyệt/từ chối, cảnh báo license.

## 10. Mẹo sử dụng hiệu quả

1. Ghi **bối cảnh + cách xử lý** vào card, không chỉ "đã xong" → người sau đọc lại được.
2. Dùng `parentKey` cho việc lớn → nhìn cây là hiểu tiến độ.
3. Hỏi AI trước khi hỏi đồng nghiệp: *"ai từng xử lý lỗi này?"*.
4. Đặt hạn chót thực tế — dashboard và lịch đều dựa vào đó.
