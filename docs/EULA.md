# ARGOS WORKS — END USER LICENSE AGREEMENT (EULA) & DATA PROCESSING TERMS

**Phiên bản**: 1.0.0 (Doanh nghiệp On-Premise)  
**Ngày hiệu lực**: 2026-10-23  
**Áp dụng cho**: Khách hàng tổ chức, doanh nghiệp triển khai ARGOS WORKS trên hạ tầng nội bộ (On-Premise / Private Cloud).

---

## 1. Phạm vi cấp phép (Grant of License)

1.1. **Mô hình cấp phép**: ARGOS WORKS được cấp phép theo mô hình **On-Premise Instance**. Mỗi giấy phép thương mại (Commercial License) cho phép Khách hàng triển khai và vận hành phần mềm trên một cụm máy chủ nội bộ hoặc đám mây riêng biệt thuộc quyền kiểm soát trực tiếp của Khách hàng.  
1.2. **Quyền sử dụng**: Khách hàng được cấp quyền sử dụng không độc quyền (non-exclusive), không thể chuyển nhượng (non-transferable), phục vụ toàn bộ nhân sự nội bộ theo số lượng người dùng (seats) hoặc theo gói Enterprise không giới hạn được thỏa thuận trong Đơn đặt hàng (Order Form).  
1.3. **Giới hạn**: Khách hàng không được bán lại, phân phối lại dưới dạng dịch vụ điện toán đám mây công cộng (Public SaaS), cho thuê hoặc đảo ngược kỹ thuật (reverse engineer) các thành phần được đóng gói bảo vệ mà không có sự đồng ý bằng văn bản từ nhà phát triển.
1.4. **Cơ chế bảo vệ bản quyền**: License là tệp/chuỗi được ký số **Ed25519** bởi nhà phát triển, chứa tên khách hàng, số ghế (seats), ngày hết hạn và danh sách module được cấp. Phần mềm kiểm tra chữ ký này khi khởi động và khi kích hoạt; việc sửa dữ liệu cài đặt tại máy khách không làm thay đổi phạm vi bản quyền. Khi license hết hạn, phần mềm chuyển sang **chế độ chỉ đọc** nhưng **không xoá dữ liệu** của Khách hàng.

---

## 2. Cam kết cư trú dữ liệu & Bảo mật (Data Sovereignty & Privacy)

2.1. **100% On-Premise / Local-First**: Toàn bộ dữ liệu nghiệp vụ — cơ sở dữ liệu (SQLite hoặc PostgreSQL), chỉ mục vector, tài liệu đính kèm, lịch sử trao đổi AI và nhật ký kiểm toán — được lưu trữ trên hệ thống lưu trữ do Khách hàng kiểm soát. Nhà phát triển **không** vận hành máy chủ dữ liệu và **không** có quyền truy cập mặc định.  
2.2. **Không thu thập Telemetry**: ARGOS WORKS **không gửi bất kỳ dữ liệu hoạt động, thống kê hay mã định danh nào** về máy chủ của nhà phát triển theo mặc định (Zero Default Telemetry). Mọi giao tiếp ra ngoài mạng nội bộ chỉ diễn ra khi Khách hàng chủ động kích hoạt:
   - Gọi API AI bên ngoài (OpenAI, Google Gemini, Ollama...) thông qua API Key do chính Khách hàng cấp và quản lý.
   - Đồng bộ chiều với máy chủ Jira Cloud của Khách hàng theo cấu hình được cung cấp.
2.3. **Bảo mật phiên & Kiểm soát truy cập**:
   - Xác thực người dùng thông qua mã hóa mật khẩu PBKDF2 / SHA-256 kèm muối (Salt).
   - Phiên đăng nhập được quản lý bằng HttpOnly, Secure, SameSite Cookie với thời hạn hiệu lực (Session TTL).
   - Cơ chế phòng chống tấn công dò mật khẩu (Brute-Force Rate Limiting) tự động khóa tạm thời IP và tài khoản khi phát hiện dấu hiệu bất thường.

---

## 3. Chính sách Sao lưu, Phục hồi & Hủy dữ liệu (Backup & Data Retention)

3.1. **Trách nhiệm sao lưu**:
   - Hệ thống trang bị module quản lý sao lưu (Backup Manager) hỗ trợ sao lưu định kỳ: với SQLite dùng Online Backup API + `integrity_check`; với PostgreSQL dùng `pg_dump -Fc`.
   - Bản sao lưu là tệp `.tar.gz` gồm database và file đính kèm, kèm mã SHA-256 để đối chiếu.
   - Khách hàng có toàn quyền tùy biến thư mục lưu trữ sao lưu: ổ đĩa cục bộ, ổ chia sẻ mạng (NAS), hoặc thư mục đồng bộ đám mây của doanh nghiệp.
3.2. **Toàn vẹn và Phục hồi (1-Click Restore)**:
   - Các bản sao lưu nén định dạng `.tar.gz` chứa đầy đủ cơ sở dữ liệu, metadata và file đính kèm.
   - Tính năng xác minh tính toàn vẹn (Integrity Verification) tự động kiểm tra tính hợp lệ trước khi cho phép khôi phục hệ thống.
3.3. **Thanh lý & Chấm dứt hợp đồng**:
   - Khi hợp đồng dịch vụ chấm dứt, Khách hàng giữ toàn quyền sở hữu 100% dữ liệu đã phát sinh trong suốt quá trình vận hành.
   - Khách hàng có thể xuất toàn bộ dữ liệu ra các định dạng chuẩn (SQLite DB, JSON, CSV, Attachments) và hủy cài đặt instance mà không phụ thuộc vào bất kỳ nhà cung cấp nào (No Vendor Lock-in).

---

## 4. Dịch vụ Hỗ trợ & Bảo hành (Support & SLA)

4.1. **Cập nhật & Bản vá an ninh**: Nhà phát triển cam kết cung cấp các bản vá lỗi bảo mật (Security Patches) và cải tiến phần mềm theo thỏa thuận bảo trì (Maintenance & Support Agreement).  
4.2. **Giới hạn trách nhiệm**: Trừ khi có thỏa thuận SLA riêng biệt, phần mềm được cung cấp trên nguyên tắc bảo đảm tuân thủ đúng chức năng thiết kế; nhà phát triển không chịu trách nhiệm đối với các sự cố mất mát dữ liệu phát sinh từ việc Khách hàng không duy trì chính sách sao lưu định kỳ hoặc để lộ thông tin xác thực quản trị.

---

## 5. Liên hệ & Hỗ trợ Kỹ thuật

Mọi yêu cầu hỗ trợ triển khai, thẩm định an toàn thông tin (Security Audit) hoặc ký kết thỏa thuận Xử lý Dữ liệu Doanh nghiệp (DPA), vui lòng liên hệ:
- **Email**: security@argosworks.com / enterprise@argosworks.com
- **Website**: https://argosworks.com
