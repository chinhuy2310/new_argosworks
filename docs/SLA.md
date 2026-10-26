# ARGOS WORKS — SLA & Chính sách Hỗ trợ (mẫu cho hợp đồng SME)

> Mẫu điều khoản dịch vụ cho gói on-premise. Chỉnh theo hợp đồng thực tế trước khi ký.

## 1. Phạm vi

Áp dụng cho phần mềm ARGOS WORKS cài đặt tại hạ tầng khách hàng (on-premise).
Nhà cung cấp **không** vận hành máy chủ, không có quyền truy cập dữ liệu khách nếu không được yêu cầu bằng văn bản.

## 2. Mức dịch vụ hỗ trợ

| Hạng mục | Standard | Premium |
|---|---|---|
| Kênh tiếp nhận | Email / ticket | Email + hotline + kênh chat riêng |
| Giờ hỗ trợ | 09:00–18:00, T2–T6 | 24/7 cho sự cố P1 |
| Phản hồi P1 (hệ thống không dùng được) | ≤ 8 giờ làm việc | ≤ 2 giờ |
| Phản hồi P2 (chức năng chính lỗi) | ≤ 1 ngày làm việc | ≤ 4 giờ |
| Phản hồi P3 (lỗi nhỏ / câu hỏi) | ≤ 3 ngày làm việc | ≤ 1 ngày |
| Bản vá bảo mật nghiêm trọng | ≤ 5 ngày làm việc | ≤ 72 giờ |
| Cập nhật phiên bản | Theo quý | Theo quý + bản vá ưu tiên |
| Diễn tập restore cùng khách | 1 lần/năm | 2 lần/năm |

**Định nghĩa P1**: toàn bộ người dùng không đăng nhập/không truy cập được; mất dữ liệu; lỗ hổng bảo mật đang bị khai thác.

## 3. Trách nhiệm của khách hàng

- Duy trì hạ tầng đạt yêu cầu tối thiểu (xem `ADMIN_GUIDE.md` mục 2).
- Backup định kỳ và **diễn tập restore**; lưu `.env` ở nơi an toàn.
- Không tự sửa mã nguồn/database khi chưa có hướng dẫn.
- Cung cấp log, ảnh chụp màn hình, thời điểm lỗi khi mở ticket.
- Cập nhật bản vá bảo mật trong vòng 30 ngày kể từ ngày phát hành.

## 4. Loại trừ

Không thuộc phạm vi SLA: sự cố do hạ tầng mạng/máy chủ của khách, do khách tự sửa mã nguồn, do hết hạn license (hệ thống chuyển read-only theo thiết kế), do dịch vụ bên thứ ba (Jira/AI cloud/Ollama), hoặc do thiên tai.

## 5. Thời gian khắc phục & bồi hoàn

- Không cam kết uptime tuyệt đối với bản on-premise (uptime phụ thuộc hạ tầng khách).
- Nếu vi phạm thời gian phản hồi P1 quá 2 lần trong 1 quý: gia hạn license thêm 01 tháng.

## 6. Bảo mật thông tin

- Nhà cung cấp chỉ truy cập hệ thống khách khi có **phiếu đồng ý bằng văn bản** cho từng lần, có thời hạn.
- Mọi truy cập từ xa (nếu có) được ghi log và báo lại cho khách.
- Không sao chép dữ liệu khách ra ngoài; mẫu dữ liệu chẩn đoán phải được ẩn danh.

## 7. Chấm dứt hợp đồng

- Khi hết hợp đồng: license chuyển read-only (dữ liệu **không** bị xoá).
- Khách có 90 ngày để export dữ liệu (Excel/CSV/backup `.tar.gz`).
- Sau 90 ngày, nhà cung cấp không giữ bản sao dữ liệu nào (không có bản sao từ đầu).

## 8. Đầu mối liên hệ

| Vai trò | Thông tin |
|---|---|
| Hỗ trợ kỹ thuật | support@<vendor-domain> |
| Kinh doanh / gia hạn license | sales@<vendor-domain> |
| Bảo mật / sự cố | security@<vendor-domain> |
