# SƠ ĐỒ VÀ ĐẶC TẢ LUỒNG NGHIỆP VỤ TOÀN DIỆN (ARGOS WORKS)

Hệ thống **ARGOS WORKS** là nền tảng quản trị công việc nội bộ, số hóa thông số kỹ thuật sản phẩm (PIM), điều hành lịch biểu và trợ lý AI doanh nghiệp được tích hợp hai chiều với **Atlassian Jira Cloud**.

Tài liệu này hệ thống hóa toàn bộ các luồng nghiệp vụ chính của hệ thống từ lúc khởi tạo người dùng cho đến khi vận hành và quản trị.

---

## 1. Bản đồ tổng thể hệ thống (System Architecture Overview)

```mermaid
flowchart TD
    subgraph Users["Người dùng & Vai trò (RBAC)"]
        Admin["👑 System Admin"]
        Manager["👔 Department Manager"]
        Member["👤 Team Member"]
        Viewer["👁️ Viewer (Read-only)"]
        Guest["🌐 Guest (Chưa đăng nhập)"]
    end

    subgraph Portals["Giao diện chính (Frontend)"]
        HomePortal["Trang chủ / Home Portal"]
        DashView["Bảng điều khiển / Dashboard"]
        CanvasModal["Chi tiết công việc / Canvas"]
        SubmitView["Đăng ký công việc / Submit"]
        PimView["Quản lý sản phẩm / PIM"]
        SchedView["Lịch biểu & Nghỉ phép / Calendar"]
        SettingsView["Cài đặt hệ thống / Settings"]
        ChatView["Trợ lý AI / Copilot"]
    end

    subgraph CoreEngine["Khối xử lý nghiệp vụ (Backend Engine)"]
        AuthRBAC["Xác thực & Kiểm soát phân quyền (Auth / RBAC)"]
        TaskEngine["Quản lý vòng đời công việc (Task Engine)"]
        JiraSync["Đồng bộ 2 chiều Jira Cloud (Jira Sync)"]
        PimEngine["Quản lý danh mục & đặc tả kỹ thuật (PIM)"]
        SchedEngine["Duyệt nghỉ phép & Điều phối lịch (Schedule)"]
        AiRagEngine["Trợ lý RAG AI & Phân tích dữ liệu (Voyage/Gemini/Claude)"]
        AuditEngine["Nhật ký kiểm toán & Sao lưu phục hồi (Audit & DR)"]
    end

    subgraph Storage["Cơ sở dữ liệu & Tệp tin"]
        DB[(Argos DB - SQLite/PostgreSQL)]
        AttachStore[Kho tệp tin & Ảnh đính kèm]
        VectorStore[(Vector Store / TF-IDF Index)]
        JiraCloud[(Atlassian Jira Cloud API)]
    end

    Users --> Portals
    Portals --> CoreEngine
    CoreEngine --> Storage
    JiraSync <--> JiraCloud
```

---

## 2. Luồng 1: Xác thực, Đăng ký & Phê duyệt tài khoản (User Onboarding & Approval)

Mọi tài khoản đăng ký mới đều phải trải qua luồng phê duyệt an toàn bởi Quản trị viên hệ thống để ngăn ngừa truy cập trái phép.

```mermaid
sequenceDiagram
    autonumber
    actor User as Người dùng mới
    participant UI as Giao diện (auth.js)
    participant Server as Backend (auth_handlers.py)
    participant DB as Database (users table)
    actor Admin as Quản trị viên (Admin)

    User->>UI: Điền thông tin (Tên, Email, Mật khẩu, Chọn phòng ban)
    UI->>Server: POST /api/account/register
    Server->>DB: Kiểm tra trùng lặp email/username
    alt Tài khoản đã tồn tại
        Server-->>UI: 400: Tài khoản đã tồn tại
    else Đăng ký thành công
        Server->>DB: Lưu tài khoản (status: 'pending', is_active: 0)
        Server-->>UI: 200: Đăng ký thành công, chờ Admin phê duyệt
    end

    Note over Admin,Server: Quản trị viên nhận thông báo và duyệt tại Cài đặt > Người dùng
    Admin->>UI: Bấm [Phê duyệt] hoặc [Từ chối]
    UI->>Server: POST /api/admin/users/approve hoặc reject
    Server->>DB: Cập nhật status: 'active', cấp vai trò (role)
    Server-->>UI: 200: Đã kích hoạt tài khoản

    User->>UI: Đăng nhập (Email/Username + Password)
    UI->>Server: POST /api/account/login
    Server->>DB: Xác thực PBKDF2 / SHA256 Password Hash
    Server-->>UI: Cấp Session Token (Cookie / Bearer) + Role Profile
    UI->>UI: Điều hướng vào Home Portal tương ứng với Role
```

---

## 3. Luồng 2: Vòng đời công việc & Đồng bộ Jira Cloud (Task Lifecycle & Sync)

```mermaid
flowchart TD
    Start([Bắt đầu: Phát sinh công việc]) --> InputMethod{Cách thức tạo task}

    InputMethod -->|Giao diện nhập liệu| FormSubmit["Nhập Form: Tiêu đề, Phòng ban, Category, Assignee, Hạn chót"]
    InputMethod -->|Trợ lý AI| AiSubmit["Chat AI phân tích tệp/ảnh và tự động tạo Task"]
    InputMethod -->|Jira Webhook / Cron| JiraImport["Đồng bộ từ Jira Cloud về Argos"]

    FormSubmit --> RBACCheck{Kiểm tra quyền tạo}
    RBACCheck -->|Member| LockDept["Khóa cứng vào phòng ban của mình"]
    RBACCheck -->|Manager / Admin| FreeDept["Chọn bất kỳ phòng ban nào"]

    LockDept --> SaveLocal["Ghi dữ liệu vào Argos DB & Sinh mã thẻ Prefix-Số"]
    FreeDept --> SaveLocal

    SaveLocal --> CheckJiraConfig{Phòng ban có liên kết Jira?}
    CheckJiraConfig -->|Có Jira Key| PushJira["Gọi Jira REST API tạo Issue / Subtask"]
    CheckJiraConfig -->|Không có| LocalOnly["Lưu trữ nội bộ (Local Record)"]
    PushJira --> BindJiraKey["Gán Jira Issue Key vào bản ghi"]

    BindJiraKey --> StatusTodo["Trạng thái: 예정 (Chờ xử lý)"]
    LocalOnly --> StatusTodo

    StatusTodo --> StatusInProg["Trạng thái: 진행 (Đang thực hiện)"]

    StatusInProg --> ActionReview["Assignee hoàn thành công việc: Gửi 검토 (Chờ duyệt)"]
    ActionReview --> NotifMgr["Gửi thông báo Realtime SSE cho Trưởng phòng & Admin"]

    NotifMgr --> ApprovalDecision{Trưởng phòng / Admin duyệt?}
    ApprovalDecision -->|Yêu cầu bổ sung| StatusInProg
    ApprovalDecision -->|Đạt yêu cầu| StatusDone["Trạng thái: 완료 (Hoàn thành)"]

    StatusDone --> AutoSyncJira["Tự động đóng Transition trên Jira Cloud tương ứng"]
    AutoSyncJira --> End([Kết thúc nhiệm vụ])
```

---

## 4. Luồng 3: Quản trị sản phẩm & Đặc tả thông số kỹ thuật (PIM Workflow)

Hệ thống PIM là nơi lưu trữ danh mục thiết bị phần cứng, giải pháp AI, mã đăng ký đấu thầu nhà nước (조달) và tài liệu kỹ thuật.

```mermaid
flowchart LR
    subgraph PIMRoles["Phân cấp quyền PIM"]
        AdminRole["👑 Admin & Mọi Manager"]
        MemberRole["👤 Member & Viewer"]
    end

    subgraph PIMActions["Thao tác PIM"]
        CreateEdit["Thêm mới / Sửa thông số & Giá bán"]
        UploadDoc["Tải ảnh thiết bị & Datasheet PDF"]
        ViewCatalog["Xem thông số, tải Datasheet, copy mã 조달"]
    end

    AdminRole -->|Toàn quyền ghi| CreateEdit
    AdminRole -->|Tải lên| UploadDoc
    MemberRole -->|Chỉ đọc / Tra cứu| ViewCatalog
    CreateEdit --> AuditLog["Ghi nhận lịch sử thay đổi giá & cấu hình"]
    UploadDoc --> ImageOptimizer["Tự động tối ưu nén ảnh & bảo mật tệp"]
```

---

## 5. Luồng 4: Điều phối Lịch biểu & Phê duyệt nghỉ phép (Calendar & Leave Approval)

```mermaid
sequenceDiagram
    autonumber
    actor Member as 👤 Nhân viên (Member)
    participant UI as Giao diện Lịch (calendar.js)
    participant Server as Backend (schedule_handlers.py)
    actor Mgr as 👔 Trưởng phòng (Manager)

    Member->>UI: Bấm [Đăng ký lịch / Xin nghỉ phép]
    UI->>Server: POST /api/schedule (title, ngày, loại: nghỉ phép/công tác)
    Server->>Server: Gán trạng thái 'pending' cho đơn xin nghỉ
    Server-->>UI: 200: Tạo thành công, đang chờ duyệt
    Server-)Mgr: Bắn thông báo Realtime: Có đơn xin nghỉ mới từ phòng ban

    Note over Mgr: Trưởng phòng mở xem danh sách cần duyệt
    Mgr->>UI: Bấm [Chấp thuận (Approve)] hoặc [Từ chối (Reject)]
    UI->>Server: POST /api/schedule/approve (id, action, reason)
    Server->>Server: Kiểm tra quyền: Manager chỉ được duyệt nhân viên cùng phòng ban
    Server-->>UI: 200: Cập nhật trạng thái 'approved'
    Server-)Member: Gửi thông báo đến Nhân viên: Đơn nghỉ phép đã được phê duyệt
    UI->>UI: Hiển thị sự kiện lên bảng lịch chung của bộ phận
```

---

## 6. Luồng 5: Trợ lý AI Thông minh & Bảo vệ dữ liệu RAG (AI Copilot Engine)

Trợ lý ảo AI sử dụng công nghệ tìm kiếm kết hợp (Hybrid Search: Vector Embedding + Fulltext) và tuân thủ tuyệt đối phạm vi phân quyền của người hỏi:

```mermaid
flowchart TD
    UserQuery["Người dùng nhập câu hỏi vào Trợ lý AI"] --> AuthIdentify["Nhận diện vai trò & Phòng ban của User"]
    AuthIdentify --> SearchRAG["Truy vấn cơ sở tri thức (Argos Vector Store + SQL)"]

    SearchRAG --> FilterSecurity{Áp dụng bộ lọc bảo mật RBAC}
    FilterSecurity -->|User là Member| OwnDeptOnly["Chỉ lấy dữ liệu công việc và tài liệu thuộc phòng mình"]
    FilterSecurity -->|User là Manager / Admin| CrossDept["Được phép lấy dữ liệu công việc toàn công ty"]

    OwnDeptOnly --> ContextGen["Tổng hợp ngữ cảnh (Context Injection)"]
    CrossDept --> ContextGen

    ContextGen --> PromptEngineering["Ghép Prompt hệ thống: Vai trò trợ lý điều hành"]
    PromptEngineering --> LLM["Gửi yêu cầu tới mô hình AI (Claude / Gemini / GPT)"]
    LLM --> StreamResponse["Truyền kết quả phản hồi Streaming (Server-Sent Events)"]
    StreamResponse --> RenderUI["Hiển thị câu trả lời kèm Trích dẫn nguồn dữ liệu"]
```

---

## 7. Luồng 6: Quản trị hệ thống, Báo cáo & Phục hồi sau thảm họa (Disaster Recovery & Governance)

```mermaid
flowchart TD
    subgraph Periodic["Tác vụ tự động / Định kỳ"]
        AutoCron["Bộ lập lịch nội bộ (Daemon Runner)"]
        AutoCron -->|Mỗi 6 tiếng| AutoBackup["Tự động sao lưu SQLite DB & thư mục đính kèm"]
        AutoCron -->|Hàng ngày| LicenseCheck["Kiểm tra trạng thái thời hạn bản quyền"]
    end

    subgraph AdminActions["Thao tác của Quản trị viên (Admin Area)"]
        UploadTpl["Tải lên mẫu Excel báo cáo công việc (.xlsx)"]
        ManualBackup["Tạo bản sao lưu an toàn trước khi cập nhật"]
        RestoreDB["Phục hồi dữ liệu từ bản sao lưu (Safety / Auto)"]
        AuditInspect["Tra cứu và xuất file Excel nhật ký kiểm toán (Audit Logs)"]
    end

    subgraph Output["Sản phẩm đầu ra"]
        ExcelReport["File Báo cáo tuần chuẩn định dạng doanh nghiệp"]
        SecureArchive["Gói lưu trữ dự phòng (data/backups/*.db)"]
        AuditReport["File báo cáo an ninh thông tin"]
    end

    UploadTpl --> ExcelReport
    ManualBackup --> SecureArchive
    RestoreDB -.->|Rollback dữ liệu| AutoBackup
    AuditInspect --> AuditReport
```

---

## 8. Ma trận đối chiếu Quyền hạn & Tính năng (RBAC Matrix)

| Chức năng nghiệp vụ | Quản trị viên (`admin`) | Trưởng phòng (`manager`) | Nhân viên (`member`) | Khách nội bộ (`viewer`) |
| :--- | :---: | :---: | :---: | :---: |
| **Tạo Task mới** | Bất kỳ phòng nào | Bất kỳ phòng nào | Khóa cứng phòng mình | ❌ Không có quyền |
| **Chỉnh sửa thông tin Task** | Toàn bộ | Chỉ sửa việc phòng mình | Chỉ sửa việc do mình phụ trách | ❌ Không có quyền |
| **Duyệt hoàn thành Task (`완료`)** | Toàn bộ | Chỉ duyệt việc phòng mình | ❌ Cần gửi `검토` cho sếp | ❌ Không có quyền |
| **Xóa Task** | Toàn bộ | Chỉ xóa việc phòng mình | ❌ Không có quyền | ❌ Không có quyền |
| **Đẩy Task sang Jira Cloud** | ✅ Có | ✅ Chỉ việc phòng mình | ❌ Không có quyền | ❌ Không có quyền |
| **Quản trị sản phẩm (PIM)** | Toàn quyền | Toàn quyền (Tất cả Manager) | Chỉ xem | Chỉ xem |
| **Duyệt nghỉ phép (Calendar)** | Toàn quyền | Duyệt nhân viên phòng mình | ❌ Chỉ được tạo đơn | ❌ Không có quyền |
| **Truy cập Tab Cài đặt (Settings)** | Toàn bộ 9 mục | Chỉ 2 mục (Template & Quy cách sản phẩm) | ❌ Ẩn tab | ❌ Ẩn tab |
| **Sao lưu & Phục hồi DB (DR)** | Toàn quyền | ❌ Ẩn tab | ❌ Ẩn tab | ❌ Ẩn tab |
| **Trợ lý AI tra cứu chéo phòng ban** | Được phép | Được phép | ❌ Chỉ tra cứu việc phòng mình | ❌ Chỉ tra cứu public |
