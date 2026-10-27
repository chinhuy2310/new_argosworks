ARGOS WORKS - HƯỚNG DẪN CÀI ĐẶT DOCKER OFFLINE (BẢO VỆ MÃ NGUỒN)
===================================================================

1. ĐIỀU KIỆN TIÊN QUYẾT:
   - Máy tính đã cài đặt Docker Desktop (trên Windows/macOS) hoặc Docker Engine (trên Linux).

2. CÁCH KHỞI ĐỘNG (1-CLICK):
   - Trên Windows: Bấm đúp vào file "start.bat".
   - Trên Linux / macOS: Mở terminal, chạy lệnh: bash start.sh
   (Trình duyệt sẽ tự động mở trang đăng nhập tại https://localhost/ hoặc http://localhost:8080)

3. CÁCH TẮT HỆ THỐNG:
   - Trên Windows: Bấm đúp vào file "stop.bat".
   - Trên Linux / macOS: Chạy lệnh: bash stop.sh

4. ĐẶC ĐIỂM BẢO MẬT:
   - Bộ đóng gói này sử dụng Docker Image đã được biên dịch sang mã máy C (Nuitka).
   - Tuyệt đối không chứa mã nguồn Python thô (.py) bên trong.
   - Cơ sở dữ liệu PostgreSQL 16 và Caddy HTTPS đã được tích hợp tự động 100%.
   - Toàn bộ dữ liệu của bạn được lưu an toàn trong thư mục "data/".
