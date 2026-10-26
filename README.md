# GarageAI

Hệ thống quản lý garage ô tô bằng **FastAPI + SQLite + React**, có trợ lý AI hỗ trợ tóm tắt lịch sử sửa chữa, giải thích dịch vụ và tạo báo giá nháp.

## Chạy dự án

### 1. Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8014 --reload
```

API chạy tại `http://127.0.0.1:8014`, Swagger tại `http://127.0.0.1:8014/docs`.
Đường dẫn chuẩn của API là `/api/v1/...` (ví dụ `http://127.0.0.1:8014/api/v1/dashboard`).

### 2. Frontend

Mở terminal khác:

```bash
npm install
npm run dev -- --host 127.0.0.1
```

Giao diện chạy tại `http://127.0.0.1:5173`.

> Lưu ý: file `.env` phải có `VITE_API_URL=http://127.0.0.1:8014` để frontend gọi đúng backend.

### Chạy nhanh cả hai server (Windows)

```powershell
.\start.ps1
```

Script sẽ khởi động backend ở cổng `8014` và frontend ở cổng `5173`. Nếu cần tự nạp lại backend khi thay đổi mã nguồn, chạy lệnh backend ở mục 1 với `--reload`.

### Tài khoản dùng thử

```text
Admin:         admin@garage.vn       / Admin@123
Quản lý:       manager@garage.vn     / Manager@123
Lễ tân:        reception@garage.vn   / Reception@123
Kỹ thuật viên: technician@garage.vn  / Technician@123
Thu ngân:      cashier@garage.vn     / Cashier@123
Khách hàng:    customer@garage.vn    / Customer@123
```

Tại màn hình đăng nhập có danh sách đăng nhập nhanh. Chỉ cần nhấn vào vai trò mong muốn, không cần nhập thông tin thủ công.

Người dùng cũng có thể đăng ký tài khoản mới trên màn hình đăng nhập. Vì lý do an toàn, tài khoản tự đăng ký được cấp vai trò `Lễ tân`; quyền quản lý không thể tự cấp từ trình duyệt.

Phiên đăng nhập được ký tại backend và có thời hạn 12 giờ. Hãy thay `AUTH_SECRET` trong `.env` khi triển khai thật.

## Phân quyền theo vai trò (RBAC)

Hệ thống áp dụng RBAC ở cả backend lẫn frontend:

- **Authentication (xác thực):** mọi API nghiệp vụ yêu cầu header `Authorization: Bearer <token>`. Thiếu hoặc sai token trả về `401`.
- **Authorization (kiểm tra quyền):** `backend/permissions.py` định nghĩa bảng vai trò → quyền. Dependency `require_permission("<quyền>")` chặn truy cập và trả `403` khi vai trò không đủ quyền.
- **Role-based routing (điều hướng theo vai trò):** sau khi đăng nhập, người dùng được đưa về trang mặc định của vai trò; menu chỉ hiển thị chức năng mà vai trò được phép.
- **Role-based dashboard (dashboard riêng theo vai trò):** trang Tổng quan hiển thị nội dung khác nhau cho từng vai trò (điều hành, lễ tân, kỹ thuật, thu ngân, khách hàng).

| Vai trò | Quyền chính |
| --- | --- |
| Admin | Toàn quyền (`*`) |
| Quản lý | Tất cả nghiệp vụ + nhân viên |
| Lễ tân | Lịch hẹn, khách hàng, xe, dịch vụ |
| Kỹ thuật viên | Phiếu sửa chữa, xe, kho phụ tùng |
| Thu ngân | Hóa đơn, khách hàng, xe |
| Khách hàng | Chỉ xem tổng quan cá nhân |

Kiểm tra phân quyền bằng API (chỉ Admin/Quản lý):

```text
GET /api/v1/rbac/roles    # danh sách vai trò và quyền tương ứng
```

## Hội thoại trợ lý AI nhiều lượt

- Trong **Trung tâm trợ lý AI → Hỏi đáp trực tiếp** hoặc ngăn trợ lý, mỗi cuộc trò chuyện có ID riêng và chỉ tài khoản tạo mới được đọc/gửi/xóa. Tin nhắn gốc được lưu đầy đủ trong SQLite (`ai_conversations`, `ai_messages`, migration `018`); tải lại trang/đăng nhập lại sẽ tải từ API, không lấy lịch sử từ browser. Trình duyệt chỉ nhớ ID hội thoại đang mở.
- Chat gửi câu hỏi và `request_id` chống gửi trùng; backend lấy lịch sử **đúng cuộc trò chuyện**, thông tin xe theo quyền, nguồn và giá phụ tùng hiện tại. Lịch sử đưa cho mô hình bị giới hạn dung lượng; `context_summary` giữ tham chiếu mã phụ tùng, thông tin khách đã báo và câu hỏi đang chờ (không coi lời khách là thông số xe đã xác minh). Bản tin gốc không bị cắt.
- Khi khách hỏi tiếp “cái nào phù hợp?” sau khi tra giá bugi, backend đọc lại các mã vừa nêu theo ID. Thiếu đời/động cơ thì hỏi; chỉ xác nhận lựa chọn khi có quy tắc tương thích đủ chi tiết, vẫn cần đối chiếu VIN trước khi lắp. Giá lấy lại từ danh mục, không từ tin nhắn cũ.
- **Cuộc trò chuyện mới** không xóa lịch sử. Xóa cần xác nhận và chỉ xóa cuộc trò chuyện được chọn cùng tin nhắn của nó; audit xóa vẫn được giữ. Tin nhắn lỗi được lưu trạng thái `failed` và gửi lại bằng đúng `request_id` để không nhân đôi.

```text
GET    /api/v1/ai/conversations
POST   /api/v1/ai/conversations                 # client_key, vehicle_id hoặc plate (tùy chọn)
GET    /api/v1/ai/conversations/{id}
POST   /api/v1/ai/conversations/{id}/messages   # request_id, question
DELETE /api/v1/ai/conversations/{id}
```

Endpoint `/api/v1/ai/assistant/chat` cũ được giữ để tương thích, nhưng giao diện chat mới dùng API hội thoại lưu bền vững.

## AI tra cứu tồn kho

- Chat lưu hội thoại và `/api/v1/ai/assistant/chat` tra trực tiếp `parts.stock`, `parts.min_stock` của **kho tổng** tại lúc hỏi; chỉ mặt hàng `active=1` được tính. Hết hàng = `stock=0`; sắp hết = `0<stock<=min_stock`; không có ngưỡng thì không kết luận sắp hết. Kết quả giới hạn 20 dòng (hoặc số lượng yêu cầu, tối đa 50), có mã mặt hàng và nguồn theo ID.
- Phân quyền `inventory.view`, `inventory.view_all`, `inventory.view_low_stock`, `inventory.view_statistics`, `inventory.recommend_restock` độc lập với quyền giá vốn, giá trị và giao dịch. Hiện Admin và Quản lý có đủ quyền; Kỹ thuật viên được xem tồn và khoảng thiếu đến mức tối thiểu, không xem giá vốn. Các vai trò khác không được truy cập. Người chỉ có `inventory.view_statistics` chỉ nhận tổng hợp, không có chi tiết.
- Chỉ lọc hãng/dòng xe theo `part_fitments` đã nhập; trường mô tả `compatible` không xác nhận lắp vừa. Không có bảng kho/chi nhánh, dữ liệu giữ chỗ, nhu cầu phụ tùng chưa xuất hay mức tồn mục tiêu: không tính tồn khả dụng/thiếu theo phiếu hoặc số nhập đến mục tiêu. `repair_order_parts` ghi nhận hàng **đã xuất** và stock đã bị trừ; không trừ lần nữa. “Thiếu để đạt tối thiểu” là khoảng chênh lệch tham khảo, không phải đơn nhập.
- Để hỗ trợ nhập đến mục tiêu: bổ sung `target_stock` có ràng buộc không âm (cho phép NULL) bằng migration, form quản lý và audit thay đổi. Muốn phân kho/giữ chỗ cần mô hình tồn từng kho, phạm vi quyền theo kho và sổ giữ chỗ hợp lệ trước khi áp dụng công thức tồn khả dụng.

## AI phân tích tải lịch hẹn

- Hai luồng chat nhận câu hỏi “ngày mai có lịch không”, giờ đông/trùng, dự báo thêm xe và đề xuất giờ thay thế. Lấy ngày theo giờ Việt Nam, đọc `appointments.appointment_at` và `duration_min`; cửa sổ thống kê mặc định 60 phút từ giờ mở cửa (cấu hình `APPOINTMENT_LOAD_SLOT_MINUTES`, từ 30–120). Tính các khoảng **chồng lấn**, đếm xe riêng biệt theo ID hoặc biển số. Tổng trạng thái tách `Đang chờ`, `Đã xác nhận`, `Đã tiếp nhận`, `Đã hủy`; chỉ hai trạng thái đầu chiếm tải đặt lịch tương lai.
- Ngưỡng **cảnh báo**, không phải công suất: `APPOINTMENT_OVERLOAD_THRESHOLD=3` (có thể sửa trong môi trường). Giờ thay thế chỉ đề nghị nếu nằm trong lịch làm việc, đủ thời lượng đã lưu, dưới ngưỡng ở mọi cửa sổ liên quan và không trùng lịch đã ghi nhận của xe, khách, kỹ thuật viên hoặc nguồn lực được gán. Nếu chưa gán kỹ thuật viên/nguồn lực hoặc chưa có công suất toàn garage, không xác nhận chắc chắn còn chỗ. Chat không sửa dữ liệu; trước khi đổi giờ bằng `PATCH /api/v1/appointments/{id}`, backend yêu cầu `appointment.reschedule` và kiểm tra lại xung đột trong transaction (trừ khi người có quyền dùng `force` có chủ đích theo API cũ).
- Quyền mới `appointment.check_availability`, `appointment.recommend_reschedule`, `appointment.reschedule`, `appointment.manage` chỉ cấp cho Admin, Quản lý, Lễ tân; quyền thống kê riêng không cấp dữ liệu khách/xe. Khách hàng chỉ đọc thống kê lịch của chính mình; chưa có chi nhánh hoặc công suất tiếp nhận tổng thể để suy luận tải thực tế toàn garage. Các câu hỏi lịch trạng thái/chi tiết cũ tiếp tục qua service hiện hữu.

## Ghi nhận thanh toán tại quầy

Ứng dụng **không thu tiền hay xác nhận giao dịch QR tự động**. Thu ngân/quản lý ghi nhận số tiền đã nhận bằng tiền mặt hoặc sau khi kiểm tra khách đã quét mã QR cửa hàng. Có thể thu một phần nhiều lần, nhập ghi chú và ngày hẹn trả tiếp; backend tính số còn nợ và trạng thái. Lần thu cuối lưu thời gian tất toán theo giờ Việt Nam. Khách hàng chỉ xem hóa đơn và lịch sử trả tiền của mình; quản lý thấy bảng công nợ tổng hợp. Không được đánh dấu hóa đơn đã trả đủ bằng cách đổi trạng thái mà không ghi khoản thu thực tế.

## Ước tính thời lượng sửa chữa

- Mỗi dịch vụ có `duration_min` trong **Danh mục dịch vụ**. Khi lập báo giá, backend chụp thời lượng ước tính từng hạng mục và tổng số phút; hóa đơn sao chép snapshot này, không thay đổi khi danh mục được sửa sau đó. Hạng mục không khớp danh mục không được tự đoán thời gian.
- Khi đang sửa hoặc đã hoàn thành, kỹ thuật viên/quản lý có thể nhập **số phút thực tế** cho từng dòng dịch vụ trong phiếu. Từ ba mẫu hoàn thành trở lên, hệ thống dùng trung vị theo từng dịch vụ nếu hợp lý so với thời lượng danh mục; dữ liệu quá lệch không thay thế thời lượng gốc. Thời gian chờ phụ tùng hoặc khoảng từ mở phiếu đến đóng phiếu không được coi là công sửa thực tế.
- Trợ lý chỉ tra dữ liệu/snapshot để giải thích thời lượng, **không huấn luyện lại mô hình** và không cam kết ngày giờ giao xe. Nếu thiếu dữ liệu, cần kỹ thuật viên xác nhận.
- Danh mục demo bổ sung vệ sinh xe cơ bản, rửa ngoại thất, vệ sinh nội thất/khoang máy và các hạng mục bảo dưỡng phổ biến. Chat tra **giá và số phút hiện tại trực tiếp từ `services`**, có nguồn theo từng dịch vụ; giá demo là tham khảo và nhân viên có thể sửa trong mục Dịch vụ. Hỏi ghé buổi sáng chỉ nhận được thời lượng thao tác, **không xác nhận còn lịch trống** cho đến khi khách cung cấp ngày/giờ và hệ thống kiểm tra lịch hẹn.

## Cấu hình AI

### Tra cứu khách hàng và xe theo quyền

- Chat tra cứu khách hàng–xe bằng các truy vấn SQL cố định, có tham số tại backend; AI không tự sinh SQL.
- Quyền chi tiết gồm `customer.view`, `customer.view_all`, `vehicle.view`, `vehicle.view_all`,
  `customer_vehicle.view`, `customer_vehicle.view_all`. Câu hỏi kết hợp hóa đơn, lịch sử sửa chữa hoặc
  lịch hẹn còn phải có đủ quyền của module tương ứng.
- Khách hàng chỉ tra cứu hồ sơ xe của chính mình. Nhân viên tra cứu toàn hệ thống phải có đủ bộ quyền
  `view_all`; thống kê, tổng hợp và cách hỏi gián tiếp không bỏ qua kiểm tra này.
- Hỗ trợ số lượng xe (`đúng`, `từ ... trở lên`, `nhiều hơn`, `nhiều nhất`), hãng/mẫu, năm sản xuất,
  biển số, khách cụ thể, nhiều mẫu xe cùng lúc, lịch sử sửa chữa, hóa đơn còn nợ và lịch chờ tiếp nhận.
- Kết quả không trả số điện thoại hoặc địa chỉ. Mỗi truy vấn tối đa 20 kết quả và được ghi vào nhật ký
  tương tác AI hiện có.
- Schema hiện tại dùng `vehicles.customer_id`: một xe có một chủ hiện tại. “Đang sở hữu” nghĩa là xe
  `active` liên kết trực tiếp với khách `active`; hệ thống chưa có đồng sở hữu, lịch sử đổi chủ, chi nhánh
  hoặc phạm vi phân công nhân viên. Nếu hỏi theo chi nhánh, trợ lý thông báo thiếu dữ liệu thay vì suy đoán.

### Tra cứu lịch hẹn và tiếp nhận xe theo quyền

- Quyền AI chi tiết gồm `appointment.view`, `appointment.view_all`, `appointment.view_status`,
  `appointment.view_statistics` và `appointment.view_details`. Người chỉ có quyền thống kê không thể đổi
  cách hỏi để lấy danh sách; danh sách tên khách/biển số còn cần quyền khách hàng, xe và quan hệ tương ứng.
- Chat hỗ trợ đếm/liệt kê lịch chờ xác nhận, đã xác nhận, đã tiếp nhận, đã hủy; lọc hôm nay, ngày mai,
  tuần này; phát hiện lịch quá giờ chưa tiếp nhận, lịch tiếp nhận chưa có kỹ thuật viên/phiếu sửa chữa và
  so sánh hôm nay với hôm qua. Tất cả khoảng ngày được tính theo giờ Việt Nam rồi đổi sang UTC để truy vấn.
- Bốn trạng thái thật của lịch là `Đang chờ`, `Đã xác nhận`, `Đã tiếp nhận`, `Đã hủy`. Đang sửa/hoàn thành
  chỉ được suy ra từ `repair_orders` liên kết. Lịch đã hủy không được cộng vào tổng đang hoạt động.
- Schema chưa có trạng thái `no_show`, ca làm việc, chi nhánh hoặc bộ phận cho lịch hẹn. Trợ lý thông báo
  giới hạn này thay vì tự tạo trạng thái hay phạm vi dữ liệu.

### Bộ lọc động an toàn cho AI

- `backend/dynamic_query.py` chuyển câu hỏi thành `QueryPlan` gồm entity, danh sách `QueryCondition`,
  sắp xếp, giới hạn (tối đa 50), khoảng ngày, trường kết quả và phép nối `AND`/`OR`.
- Entity hiện hỗ trợ: hóa đơn, giao dịch thanh toán, công nợ theo khách hàng, xe theo năm sản xuất,
  phiếu sửa chữa và thống kê dịch vụ. Lịch hẹn dùng cùng nguyên tắc qua `appointment_query.py`.
- Toán tử được phép: `>`, `>=`, `<`, `<=`, `=`, `!=`, khoảng bao gồm hai đầu và tập giá trị.
  “Trên 10 triệu” là `> 10.000.000`; “từ 10 triệu trở lên” là `>= 10.000.000`.
- Tiền hóa đơn được tách thành tổng tiền, tiền đã thanh toán thực tế từ giao dịch `completed`, và số còn nợ.
  Hóa đơn đã hủy bị loại mặc định. Nếu không nêu đơn vị, hệ thống dùng VNĐ và ghi rõ trong kết quả.
- SQL chỉ được tạo từ biểu thức đã whitelist; tên bảng/cột/toán tử không lấy từ nội dung chat và mọi giá trị
  đều truyền bằng tham số. Backend kiểm tra RBAC trước khi phân tích tên khách hoặc đọc dữ liệu hạn chế.
- Hỗ trợ hôm nay/tháng này/tuần này, trước ngày, sau ngày và khoảng ngày; kết quả luôn nêu điều kiện,
  kỳ dữ liệu, đơn vị, thứ tự và giới hạn đã áp dụng. Khoảng giờ lịch hẹn thiếu ngày sẽ yêu cầu làm rõ.

### Tóm tắt lịch sử sửa chữa mở rộng

- Backend tính từ `repair_history`, `repair_orders`, hạng mục thực tế, phụ tùng thực tế và báo giá liên kết;
  hạng mục chỉ có trong báo giá không được coi là đã thực hiện.
- Bản tóm tắt giữ nội dung cũ và bổ sung 13 phần: tổng quan, tần suất 3/6/12 tháng, dòng thời gian,
  hạng mục thực tế/lặp lại, trạng thái công việc, biến động số km, nhóm bảo dưỡng, ghi chú, cảnh báo,
  độ đầy đủ và nguồn đối chiếu. Mã phiếu xuất hiện trong mọi cảnh báo có nguồn.
- Tần suất phân biệt số phiếu/bản ghi với số ngày xe vào garage; khoảng tháng được tính theo lịch Việt Nam,
  không dùng số ngày ước lượng. Hạng mục lặp được đếm tối đa một lần trong mỗi phiếu.
- Số km giảm được giữ nguyên và đánh dấu cần xác minh. Phụ tùng chỉ bị cảnh báo không phù hợp khi có quy
  tắc `part_fitments` đã lưu và không quy tắc nào khớp cấu hình xe.
- Schema chưa có trường kết quả sau sửa chữa và chưa có chu kỳ bảo dưỡng hãng gắn với xe. Hệ thống liệt kê
  cụ thể dữ liệu thiếu, không tạo điểm phần trăm và không dự đoán hạn bảo dưỡng tiếp theo.
- API trả thêm `history_summary` có cấu trúc. Giao diện giữ các khối tóm tắt hiện tại và bổ sung danh sách
  `<details>` để mở từng phiếu, xem dịch vụ, phụ tùng/mã phụ tùng, ghi chú, đề xuất và trường còn thiếu.

### Tra phụ tùng theo xe

- Hồ sơ xe lưu VIN, hãng, dòng xe, năm, phiên bản, mã động cơ và nhiên liệu. Trường còn thiếu để trống; hệ thống **không suy ra cấu hình từ VIN** nếu chưa có nguồn giải mã đã xác thực. Nhân viên có thể bổ sung trong mục **Xe → Chỉnh sửa**.
- Trong **Kho phụ tùng → Cấu hình xe**, nhân viên có quyền kho nhập quy tắc lắp vừa cho từng mã phụ tùng: hãng/dòng xe, khoảng năm và tùy chọn phiên bản, mã động cơ, nhiên liệu. Chỉ nhập thông tin đã đối chiếu với tài liệu hãng/OEM. API tương ứng: `GET/PUT /api/v1/parts/{id}/fitments`.
- Chat ưu tiên quy tắc này; phụ tùng không khớp bị loại. Nếu chưa có quy tắc, nội dung `compatible` cũ chỉ tạo **gợi ý sơ bộ**, không phải xác nhận lắp vừa. Giá và tồn kho tra tại thời điểm hỏi, không giữ hàng; kỹ thuật viên phải xác nhận mã phụ tùng/VIN và tình trạng xe trước khi đề nghị thay thế.

- Không có `OPENAI_API_KEY`: hệ thống dùng phản hồi demo an toàn để vẫn chạy được.
- Có API key: sao chép `.env.example` thành `.env`, điền key vào `OPENAI_API_KEY`.
- API key chỉ nằm ở backend, không gửi xuống trình duyệt và `.env` đã được bỏ qua bởi Git.

**Trả lời bằng mô hình cục bộ:** chạy Ollama trên chính máy backend, tải mô hình
`ollama pull qwen2.5:7b`, đặt `AI_PROVIDER=ollama` và
`OLLAMA_CHAT_MODEL=qwen2.5:7b` trong `.env`, rồi khởi động lại backend.
Backend gọi `http://127.0.0.1:11434/v1` qua giao diện tương thích OpenAI;
không cần `OPENAI_API_KEY` và không gửi ngữ cảnh cho dịch vụ AI ngoài. Tìm nguồn
FTS5/vector và kiểm tra quyền vẫn thực hiện tại backend trước khi gọi mô hình.
Nếu Ollama không chạy, yêu cầu tạo sinh sẽ báo lỗi; kiểm tra Ollama và mô hình
đã tải. Để dùng lại OpenAI, đặt `AI_PROVIDER=openai` và cấu hình key.

Prompt hệ thống yêu cầu AI chỉ dựa trên dữ liệu được cung cấp, không tự chẩn đoán và luôn đánh dấu nội dung là bản nháp cần kỹ thuật viên xác nhận.

### Chỉ mục tri thức cho RAG

**Embedding cục bộ (bước lập chỉ mục, chưa dùng trong chat):** Cài Ollama và tải
`ollama pull bge-m3`, sau đó chạy từ thư mục dự án:

```powershell
python -m backend.vector_index --model bge-m3
```

Lệnh tạo/cập nhật vector trong bảng SQLite `knowledge_vectors` cho các đoạn
`technical_chunks` thuộc bài đã xuất bản và các ca sửa chữa đã xuất bản. Bài nháp,
thu hồi hoặc xóa mềm không được lập chỉ mục; thay đổi/thu hồi nguồn sẽ xóa vector
cũ ngay. Chạy lại lệnh sau khi xuất bản hay chỉnh sửa tài liệu để tạo vector mới;
lần chạy bình thường bỏ qua đoạn không thay đổi. Dùng `--rebuild` khi thay phiên bản
mô hình embedding dưới cùng tên. Ollama cần chạy trên máy tại `127.0.0.1:11434`.
Đây mới là bước **lưu vector**, chưa thay thế tìm kiếm FTS5 hoặc tự đưa vector vào
prompt chat. Dữ liệu kỹ thuật được gửi tới Ollama *trên chính máy này*.

- Migration 014 tạo `knowledge_chunks` và chỉ mục SQLite FTS5 `knowledge_fts`. Mỗi đoạn giữ `source_type`, `source_id`, `vehicle_id`, `customer_id`, `visibility` và văn bản nguồn. Dữ liệu có trước migration được lập chỉ mục một lần; trigger cập nhật khi dịch vụ, phụ tùng, lịch sử hoặc chủ xe thay đổi.
- Dịch vụ và mô tả phụ tùng ở mức `public`; lịch sử có bản `customer` (ngày, dịch vụ, số km) và bản `internal` (thêm ghi chú). Lịch sử không gắn được xe/chủ sở hữu không vào chỉ mục. Không lập chỉ mục giá, tồn kho, giá vốn; những số liệu này luôn phải tra lại bảng nghiệp vụ.
- `GET /api/v1/ai/knowledge/search?q=phanh&vehicle_id=...` yêu cầu token; backend lọc quyền và chủ xe trong SQL trước khi trả nguồn. Chỉ mục dịch vụ/phụ tùng/lịch sử là **tầng truy xuất từ khóa FTS5**, chưa phải embeddings/vector và chưa tự động dùng làm chứng cứ tổng quát cho mọi câu trả lời. Bài kỹ thuật đã duyệt có luồng RAG riêng bên dưới; không cho AI tự quyết định chẩn đoán hay báo giá.

### Kho kiến thức kỹ thuật cho chat (FTS5 + vector cục bộ)

**Tìm kiếm kết hợp cục bộ (FTS5 + vector):** Sau khi chạy
`python -m backend.vector_index --model bge-m3` với Ollama đã cài `bge-m3`,
truy vấn bài kỹ thuật/ca sửa chữa kết hợp từ khóa và độ tương đồng ngữ nghĩa.
Đặt `LOCAL_EMBED_MODEL=bge-m3` trong môi trường backend nếu dùng mô hình khác tên mặc định
(phải trùng tên lúc lập chỉ mục). Chỉ bài đã xuất bản, không bị xóa/thu hồi và
phù hợp cấu hình xe mới được trả về. Ollama không chạy hoặc chưa lập chỉ mục thì
tự dùng FTS5; sau khi thêm/sửa tài liệu cần chạy lại lệnh lập chỉ mục để có vector mới.
Hiện phần quyết định *khi nào chat tra tài liệu* vẫn theo các triệu chứng đã nhận diện;
câu hỏi rộng chưa tự động tra mọi nguồn (thuộc bước nâng cấp tiếp theo).

Trang **Kho kiến thức kỹ thuật** dùng `GET /api/v1/ai/technical-articles?page=1&page_size=20` để tìm kiếm (không dấu), lọc kết hợp, thống kê trạng thái và phân trang tại backend; danh sách không gửi nội dung dài hoặc BLOB tệp. `GET /{id}` chỉ tải nội dung, đoạn trích và lịch sử khi mở chi tiết. Bài mới/sửa vẫn về nháp; sửa và thay tệp giữ bản chụp cũ trong `technical_article_history` (migration 025), bao gồm tệp cũ nếu có. API nhận `expected_revision` để báo xung đột `409` khi người khác sửa/duyệt trước; UI luôn gửi phiên bản đang xem. Thu hồi ghi lý do và ngừng dùng bài trong chat; xóa mềm có lý do, chỉ Admin/Quản lý thực hiện, không mất bản ghi/tệp và không đưa bài vào chat. Danh sách trạng thái chỉ phản ánh `draft`/`published` có thật, duyệt chuyên môn, và cờ thu hồi; hệ thống **chưa có quy trình từ chối/yêu cầu sửa riêng hay xác minh URL nguồn tự động**, nên không hiển thị các trạng thái đó như thể đã được duyệt.

- Vào **Trung tâm trợ lý AI → Kiến thức kỹ thuật** bằng tài khoản kỹ thuật viên/quản lý để soạn bài. Mỗi bài cần tiêu đề, triệu chứng/từ đồng nghĩa, hướng kiểm tra, cảnh báo an toàn và tên nguồn (tài liệu hãng hoặc quy trình nội bộ). Nên hỏi rõ thời điểm/vị trí tiếng kêu; không viết kết luận chắc chắn hay giá đoán.
- Khởi động backend nạp **9 bài tham khảo chung** theo nguồn công khai (gầm, phanh, vô lăng rung, lệch lái, điều hòa, khó nổ, rung giật, đèn động cơ, quá nhiệt). Các bài được đánh dấu `reviewed_by=NULL`: **đang dùng làm nguồn tham khảo cho chat nhưng chưa được garage duyệt kỹ thuật cho từng dòng xe**. Nội dung chỉ hướng dẫn hỏi và kiểm tra, không là kết luận. Admin/Quản lý nên rà soát từng bài, chọn **Duyệt xuất bản** nếu phù hợp hoặc **Thu hồi** ngay; khởi động lại sẽ không tự xuất bản lại bài đã thu hồi.
- Nếu đã có database và muốn nhập ngay mà không khởi động lại backend: chạy `python seed_technical.py` trong thư mục dự án. Lệnh không ghi đè bài có sẵn; lặp lại không tạo trùng. Database của môi trường hiện tại đã được nhập 9 bài.
- Bài do nhân viên thêm mới là **bản nháp** và không vào chat trước khi Admin/Quản lý duyệt. Sửa bất kỳ bài đã xuất bản nào cũng chuyển về nháp; **Thu hồi** loại khỏi tra cứu ngay.
- Mỗi bài hỗ trợ hãng/dòng xe, khoảng năm, mã động cơ áp dụng (để trống = bài chung), tên và URL nguồn, phiên bản tài liệu, mức cảnh báo (`low`/`medium`/`high`/`critical`). Kỹ thuật viên hoặc Quản lý/Admin bấm **Duyệt chuyên môn**; backend chụp ID tài khoản + thời điểm UTC, không nhận tên/ngày duyệt từ trình duyệt. Sau đó Admin/Quản lý mới **Duyệt xuất bản**. Sửa nội dung/thông số xe sẽ xóa phê duyệt cũ và buộc duyệt lại. Bài mẫu cũ có phiên bản/người duyệt để trống, tuyệt đối không tự điền tên người duyệt giả.
- Chat chỉ truy xuất bài theo hồ sơ xe đã được backend kiểm tra quyền. Bài giới hạn theo hãng/dòng/năm/động cơ **không xuất hiện** khi không chọn xe, khi cấu hình xe thiếu hoặc không khớp; bài chung vẫn dùng được. `GET /api/v1/ai/knowledge/search?q=...&vehicle_id=...` áp dụng cùng quy tắc. Không giải mã VIN hoặc tự đoán mã động cơ.
- Nội dung các bài hiện có cũng được tách thành đoạn. Sau khi tạo bài, nhân viên có thể **tải PDF/DOCX tối đa 5 MB** trong cùng trang; lúc này các đoạn từ tệp nguồn thay thế đoạn nội dung nhập tay (bài vẫn giữ phần tóm tắt do nhân viên viết). Backend lưu tệp/sha256 và chỉ mục FTS5 `technical_chunk_fts`. Chat chỉ tìm đoạn thuộc **bài published**, đưa tối đa hai trích đoạn mỗi bài vào ngữ cảnh AI và ghi **số đoạn** trong nhãn nguồn. Tài liệu mới tự chuyển bài về nháp và xóa phê duyệt cũ; chỉ nhân viên có quyền xem/tải tệp gốc. PDF quét ảnh hoặc PDF mã hóa cần OCR/giải mã bên ngoài, không tự suy đoán nội dung. Khi nâng cấp môi trường, cài lại `requirements.txt` để có `pypdf` và `python-multipart`.
- Migration 020 tạo `technical_articles` và chỉ mục FTS5 riêng chỉ chứa bài đã duyệt. Cả chat lưu hội thoại và `/ai/assistant/chat` đều tìm bài theo triệu chứng rồi đưa nội dung đã duyệt cho AI; khi không có API key dùng hướng dẫn từ bài gốc. Câu trả lời có `sources` loại `technical_article` và nhãn nguồn. Câu hỏi nguy cấp vẫn đi nhánh an toàn trước. Đây là **tìm kiếm từ khóa**, không phải embeddings; nếu không khớp bài phù hợp, hệ thống vẫn báo thiếu dữ liệu.
- Ví dụ: hỏi chat **“Xe chạy kêu lọc cọc thì làm sao?”** rồi mở **Xem nguồn đối chiếu**. Bài tham khảo sẽ trả lời ngay cả khi chưa có API key OpenAI; mô hình chỉ dùng bài đã truy xuất làm ngữ cảnh, không được tự chẩn đoán.

```text
GET  /api/v1/ai/technical-articles              # nhân viên kỹ thuật/quản lý
POST /api/v1/ai/technical-articles              # tạo nháp
PUT  /api/v1/ai/technical-articles/{id}         # sửa và trả về nháp
POST /api/v1/ai/technical-articles/{id}/publish   # Admin/Quản lý
POST /api/v1/ai/technical-articles/{id}/technical-review # Kỹ thuật viên/Quản lý/Admin
POST /api/v1/ai/technical-articles/{id}/document # multipart file PDF/DOCX, tự chuyển nháp
GET  /api/v1/ai/technical-articles/{id}/document # nhân viên tải tệp nguồn
POST /api/v1/ai/technical-articles/{id}/unpublish # Admin/Quản lý
GET  /api/v1/ai/knowledge/search?q=lọc+cọc     # xem mục technical đã duyệt
```

### Giải thích dịch vụ theo phiếu/hóa đơn

Các endpoint `POST /api/v1/ai/service-explanations/{order_code}`, `POST /api/v1/ai/repair-orders/{id}/service-explanation` và `POST /api/v1/ai/invoices/{id}/service-explanation` tái sử dụng context đã kiểm tra quyền ở backend. Diễn giải tiền, trạng thái và phụ tùng được dựng tất định từ chứng từ kể cả khi có `OPENAI_API_KEY`; thiếu key không còn bị hiển thị là lỗi `fallback` của tác vụ này. Trường `data_status` mới (`sourced`, `partial`, `no_data`, `error`) là metadata tùy chọn, tương thích client cũ. Chat hỏi tiếp cũng chỉ đọc cùng phiếu/hóa đơn, không cho model sinh giá hay cam kết bảo hành. Tương thích phụ tùng chỉ có thể kiểm tra bằng mã liên kết với `part_fitments` và cấu hình xe; tên gợi ý hãng khác chỉ là cảnh báo cần kiểm tra, không chứng minh sai. Schema hiện không có chính sách bảo hành xác nhận hay mô tả công dụng phụ tùng độc lập, nên cần đề xuất schema và quy trình duyệt trước khi khai báo các nội dung này là đã xác minh. Không có migration cho nâng cấp này.

**Đề xuất dữ liệu (chưa triển khai):** cần chính sách bảo hành được duyệt, có phạm vi dịch vụ/phụ tùng, thời hạn, điều kiện, ngoại lệ và phiên bản gắn chứng từ; ghi nhận hoàn thành theo từng dòng phiếu với người xác nhận/thời điểm/chứng cứ; mô tả công dụng phụ tùng có nguồn và trạng thái duyệt. Chỉ bổ sung sau khi garage thống nhất workflow và phân quyền; không tự ghi nhận từ câu trả lời AI.

### Tra cứu & báo cáo

Trang hiện có dùng `GET /api/v1/reports/overview` (kỳ theo `Asia/Ho_Chi_Minh`), thêm so sánh kỳ liền trước có cùng số ngày, `monthly_series`, tiền thực thu theo `payments.status='completed'`/ngày thanh toán và đối soát dòng hóa đơn. Bộ lọc hóa đơn chỉ áp dụng doanh thu, biểu đồ và xếp hạng; bộ lọc lịch hẹn chỉ áp dụng lịch, trạng thái phiếu chỉ áp dụng phiếu; công nợ và kho luôn là số dư hiện tại. `GET /api/v1/reports/drilldown` trả nguồn phân trang tối đa 50 dòng/trang; `GET /api/v1/reports/export` xuất đúng tập dòng đó thành CSV tối đa 5.000 dòng; `POST /api/v1/reports/explain` diễn giải tất định các phép tính được hỗ trợ. Cả ba endpoint mới yêu cầu quyền `reports`; không gửi email hay thay đổi dữ liệu. Tổng hóa đơn vẫn là `SUM(invoices.total)` chưa hủy theo ngày phát hành; tiền công/phụ tùng là dòng hóa đơn **trước** giảm giá/thuế; công nợ là `max(total-paid_amount,0)` của hóa đơn chưa hủy. Nếu dòng cũ không khớp tổng, hiển thị chênh lệch thay vì thay đổi công thức. Chưa có chi nhánh/kho nhiều địa điểm hoặc cấu hình mục tiêu bổ sung hàng; các thống kê tải lịch phức tạp tiếp tục dùng nghiệp vụ tải lịch hẹn riêng, không suy diễn công suất garage từ ngưỡng hiển thị.

### 100 bản nháp mở rộng kiến thức ô tô

`backend/technical_expansion_data.py` chứa 100 bài theo 10 nhóm (15/12/12/15/10/8/12/6/5/5): mỗi bài gồm câu hỏi phân biệt, khả năng cần kiểm tra, hạng mục đo/kiểm, xử lý có điều kiện và cảnh báo an toàn. Chạy `python import_technical_expansion.py` để xem các bài sẽ thêm; `python import_technical_expansion.py --apply` để tạo qua `ArticleIn` và `create_article`, ghi audit và chỉ mục đoạn. Chạy lại không tạo bản sao; không sửa bài cũ. `python verify_technical_expansion.py` kiểm tra database đã nạp và 5 câu hỏi mẫu.

**Quan trọng:** 5 bài ID 28, 29, 104, 107, 108 đã được xuất bản sau đối chiếu nguồn riêng. Đợt demo sau đó hoàn thiện và xuất bản 94 bài draft còn lại với nhãn AI chưa xác minh; không được trình bày chúng như tài liệu hãng/chuyên gia. Hệ thống dùng FTS5 (`technical_fts`, `technical_chunk_fts`) và đoạn `technical_chunks`, **chưa có mô hình embedding/vector cho bài kỹ thuật**.

### Xuất bản dữ liệu trình diễn AI

`publish_demo_technical_articles.py` hoàn thiện các bài draft bằng cấu trúc câu hỏi, khả năng, quy trình kiểm tra, xử lý có điều kiện, an toàn, phạm vi và giới hạn. Mọi bài do script xử lý mang nhãn **“Nội dung demo do AI tổng hợp”**, phiên bản **“Demo, chưa xác minh”** và thông báo không thay thế chẩn đoán kỹ thuật. Mặc định script chỉ dry-run; dùng `--apply`, `--review`, `--publish` cho từng bước, hoặc `--all` để xác nhận toàn bộ workflow; `--limit N` giới hạn số bài. Script dùng `ArticleIn`, optimistic locking, lịch sử/audit, tài khoản kỹ thuật viên và quản lý demo hiện có; không lưu mật khẩu/token và không cập nhật trạng thái bằng SQL.

Ngày 26/10/2026, 94 bài draft đã được hoàn thiện, kỹ thuật viên duyệt demo và quản lý xuất bản. Database hiện có **109 bài published, 0 draft**; 94 bài mang nhãn demo AI, 15 bài xuất bản trước đó giữ nguyên nguồn/nội dung. Nhãn duyệt demo chỉ phục vụ trình diễn FTS5/RAG, **không phải xác nhận của hãng hoặc chuyên gia**.

Đợt đối chiếu nguồn đầu tiên nằm ở `backend/technical_source_reviews.py`. Nguồn bổ sung cho ba bài chờ xuất bản nằm ở `backend/pending_publish_source_reviews.py`; `publish_five_pending_articles.py` cập nhật nguồn, duyệt lại và xuất bản đúng 5 bài qua workflow có history/audit. Nguồn GM và Lexus có giới hạn hãng/năm rõ ràng; bài vẫn yêu cầu tra tài liệu OEM theo VIN trước sửa. Danh sách URL ứng viên không tự trở thành nguồn đã xác minh; PDF/DOCX tự biên tập không phải nguồn độc lập.

File tham khảo theo từng bài còn thiếu: [`TECHNICAL_SOURCE_MATRIX_97.csv`](TECHNICAL_SOURCE_MATRIX_97.csv), hướng dẫn và giới hạn ở [`TECHNICAL_SOURCE_CANDIDATES.md`](TECHNICAL_SOURCE_CANDIDATES.md). Script `python -X utf8 create_technical_source_matrix.py` đối chiếu 97 bài với database để tạo lại CSV, không thay đổi trạng thái bài. Các mục ASE là danh mục kỹ năng, không phải quy trình sửa chữa theo VIN hay xác nhận từng nhận định.

### Thu thập kiến thức từ ca sửa chữa thực tế

- Khi phiếu chuyển sang **Hoàn thành**, backend tạo một **ca kiến thức nháp** trong cùng transaction (`repair_knowledge_cases`, migration 024). Từ phiếu chỉ chụp lời khách báo, ghi chú kiểm tra, tên hạng mục/phụ tùng và cấu hình xe; **không** suy ra nguyên nhân hoặc kết quả sửa chữa. Phiếu hoàn thành có trước migration được tạo nháp một lần, không ghi đè ca đã được nhân viên chỉnh sửa.
- Trong **Phiếu sửa chữa → chi tiết phiếu hoàn thành → Kiến thức từ ca sửa chữa**, nhân viên hiệu đính 5 mục: triệu chứng, kiểm tra thực tế, nguyên nhân đã xác nhận, việc đã làm, kết quả sau sửa. Kỹ thuật viên duyệt chuyên môn rồi Admin/Quản lý xuất bản. Chỉnh sửa ca đã xuất bản đưa về nháp và xóa phê duyệt cũ. Backend chặn xuất bản khi còn email, số điện thoại, biển số, VIN dạng nhận diện; quản lý vẫn phải đọc và ẩn danh thủ công trước khi duyệt.
- Chỉ ca `published` có trong `repair_case_fts`. Chat chỉ truy xuất ca khi chọn xe đã xác thực và hãng/dòng/năm/mã động cơ phù hợp; nguồn có loại `repair_case`, không chứa tên khách, biển số, VIN, giá hay ghi chú nội bộ. Ca trước chỉ là **ví dụ tham khảo**, không phải chẩn đoán cho xe hiện tại. Đây là truy xuất dữ liệu có kiểm soát, **không huấn luyện lại mô hình**.

```text
GET  /api/v1/repair-orders/{id}/knowledge-case
POST /api/v1/repair-orders/{id}/knowledge-case/capture          # phiếu hoàn thành cũ
PUT  /api/v1/repair-orders/{id}/knowledge-case                  # hiệu đính, trả về nháp
POST /api/v1/repair-orders/{id}/knowledge-case/technical-review # kỹ thuật viên
POST /api/v1/repair-orders/{id}/knowledge-case/publish          # Admin/Quản lý
POST /api/v1/repair-orders/{id}/knowledge-case/unpublish        # thu hồi khỏi chat
```

## Kiểm thử

```bash
pytest backend/tests -q
npm run build
```

Test bao phủ đăng nhập/phân quyền, lịch hẹn, xe, khách hàng, dịch vụ, phụ tùng, phiếu sửa chữa,
báo giá, hóa đơn/thanh toán, AI an toàn, báo cáo, cùng migration, ràng buộc toàn vẹn, phiên bản API,
phân trang, chống IDOR và các quy tắc bảo mật tiền tệ. Nhóm khách hàng & xe kiểm tra thêm:
tìm theo tên/SĐT/biển số/VIN, phát hiện trùng lặp, dùng lại/liên kết bản ghi hiện có và lịch sử
sửa chữa sinh ra khi phiếu hoàn thành. Nhóm lịch hẹn kiểm tra giờ/ngày làm việc, trùng kỹ thuật
viên và nguồn lực, xác nhận có kiểm soát, hủy kèm lý do và tiếp nhận không tạo phiếu trùng.
Nhóm quy trình sửa chữa kiểm tra chặn nhảy cóc trạng thái, điều kiện từng bước, phân quyền duyệt
báo giá/hủy/bàn giao, hóa đơn chưa thanh toán không được bàn giao và lịch sử trạng thái bất biến (50 test).

## Kiến trúc backend & quy ước API

Backend được tổ chức theo **module nghiệp vụ**, không dồn toàn bộ logic vào một tệp:

```text
backend/
├── main.py                 # lắp ghép ứng dụng: middleware, xử lý lỗi, gắn router
├── middleware.py           # tương thích ngược /api -> /api/v1
├── domain.py               # tiện ích nghiệp vụ dùng chung (mã phiếu, tổng tiền...)
├── workflow.py             # máy trạng thái phiếu sửa chữa, điều kiện chuyển bước, lịch sử
├── core/                   # hạ tầng dùng chung
│   ├── config.py           # cấu hình (CORS, phân trang, phiên bản)
│   ├── db.py               # truy cập SQLite, transaction
│   ├── deps.py             # xác thực + dependency phân quyền
│   ├── access.py           # kiểm soát truy cập từng bản ghi (chống IDOR)
│   ├── errors.py           # lỗi thống nhất + HTTP status
│   ├── pagination.py       # phân trang, tìm kiếm
│   ├── audit.py            # nhật ký kiểm toán (lọc dữ liệu nhạy cảm)
│   └── logging.py          # logging an toàn (không ghi body/token)
├── schemas/                # Pydantic request/response theo module
└── api/v1/                 # module nghiệp vụ
    ├── auth.py             # authentication + authorization (RBAC)
    ├── customers.py        ├── vehicles.py       ├── appointments.py
    ├── services.py         ├── parts.py          ├── repair_orders.py
    ├── quotes.py           ├── invoices.py       # hóa đơn + thanh toán
    ├── reports.py          # dashboard + báo cáo
    ├── ai.py               └── audit.py
```

**Quy ước API** (chi tiết đầy đủ: [docs/API_DESIGN.md](docs/API_DESIGN.md))

- **Có phiên bản:** mọi endpoint nghiệp vụ nằm dưới `/api/v1`. Đường dẫn cũ `/api/...` vẫn hoạt động
  nhờ middleware tương thích ngược nhưng không xuất hiện trong OpenAPI.
- **Schema rõ ràng:** mỗi module khai báo Pydantic cho request/response; `response_model` lọc đúng
  trường trả về.
- **Kiểm tra đầu vào:** giới hạn độ dài/kiểu/giá trị; trường không hợp lệ hoặc lạ bị từ chối (`422`).
- **Mã trạng thái:** `200` đọc/cập nhật, `201` tạo mới, `400` nghiệp vụ sai, `401` chưa đăng nhập,
  `403` thiếu quyền/không sở hữu, `404` không thấy, `409` xung đột, `422` dữ liệu sai, `500` lỗi hệ thống.
- **Lỗi thống nhất:**

  ```json
  {"error": {"code": "not_found", "message": "...", "details": null}, "detail": "..."}
  ```

- **Phân trang:** danh sách trả `{items, total, page, page_size, pages}`; hỗ trợ `?page=&page_size=`,
  `?q=` và bộ lọc riêng (`status`, `category`, `date`, `low_stock`, `order_id`...).
- **Không lộ dữ liệu nhạy cảm:** response không chứa `password_hash`/token nội bộ; audit lọc các khóa
  nhạy cảm; log chỉ ghi method/path/status/thời gian, không ghi body hay header.
- **Kiểm tra quyền ở backend:** mọi endpoint dùng `require_permission(...)`, không phụ thuộc việc ẩn nút
  ở frontend.
- **Chống IDOR:** ngoài RBAC, bản ghi của khách hàng được kiểm tra chủ sở hữu (`core/access.py`);
  danh sách lịch hẹn của khách hàng được giới hạn theo hồ sơ của chính họ.
- **Tiền do server tính:** `total` phiếu sửa chữa và `subtotal/tax/total/paid_amount/status` của hóa đơn
  không nhận từ client; thanh toán bị chặn nếu vượt số còn phải thu.

## Cơ sở dữ liệu

Thiết kế đầy đủ (ERD, khóa, chỉ mục, ràng buộc, quy tắc toàn vẹn, transaction) nằm trong
[`docs/DATABASE_DESIGN.md`](docs/DATABASE_DESIGN.md). DDL cấu trúc đích nằm ở `backend/schema.sql`.

**Quy ước quan trọng**

- **Tiền tệ:** lưu `INTEGER` đơn vị đồng, tính bằng `decimal.Decimal` (`backend/money.py`), không dùng floating-point.
- **Thời gian:** lưu UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`), hiển thị theo giờ Việt Nam (`backend/timeutil.py`).
- **Biển số:** chuẩn hóa vào `plate_normalized` để tra cứu, **không** đặt UNIQUE (không coi là định danh vĩnh viễn); `vin` là duy nhất một phần khi có.
- **Mật khẩu:** chỉ lưu bản băm PBKDF2-SHA256, không lưu văn bản thuần.
- **Xóa mềm:** hóa đơn/thanh toán/nhật ký dùng trạng thái, trigger chặn xóa cứng.
- **Giá tại thời điểm:** hạng mục, phụ tùng, báo giá lưu snapshot đơn giá và thành tiền.

**Migration** (`backend/migrations.py`, bảng theo dõi `schema_migrations`):

```text
001_initial_schema        # tạo toàn bộ bảng theo cấu trúc đích
002_upgrade_legacy_core   # nâng cấp dữ liệu từ cấu trúc cũ (rebuild table + chuyển đổi dữ liệu)
003_indexes_and_guards    # chỉ mục, trigger updated_at, trigger chặn xóa cứng
004_vehicle_history_link  # liên kết lịch sử sửa chữa với phiếu (chống ghi trùng bằng unique index)
005_appointment_scheduling # bảng nguồn lực + phân công kỹ thuật viên/nguồn lực, trạng thái xác nhận/hủy
006_appointment_reuse_order # nhiều lịch của cùng xe được trỏ về đúng một phiếu đang mở
007_repair_order_workflow  # mã trạng thái, dữ liệu tiếp nhận/kỹ thuật, mốc thời gian, lịch sử bất biến
008_inventory_transactions  # sổ nhập/xuất/hoàn kho, khóa idempotency chống trừ kho hai lần
009_quote_invoice_payment_integrity # thời hạn báo giá, snapshot hóa đơn, chống trùng thanh toán
019_payment_lifecycle       # phân biệt thanh toán hợp lệ/thất bại/hủy/hoàn tiền
```

Migration chạy tự động khi khởi động backend (`init_db`). Cơ sở dữ liệu cũ được nâng cấp tại chỗ,
giữ nguyên dữ liệu (chuẩn hóa biển số, chuyển giờ VN → UTC, làm tròn tiền về đồng, liên kết xe/khách/kỹ thuật viên).
Migration `007` rebuild `repair_orders`, bổ sung `status_code`/dữ liệu tiếp nhận/kỹ thuật, backfill
tình trạng ban đầu và yêu cầu khách hàng từ ghi chú cũ, đồng thời tạo bảng lịch sử trạng thái và
trigger chặn sửa/xóa lịch sử.

**Bảng dữ liệu:** `users`, `customers`, `vehicles`, `services`, `parts`, `appointments`,
`repair_orders`, `repair_order_status_history`, `repair_order_items`, `repair_order_parts`,
`repair_notes`, `quotes`, `quote_items`, `invoices`, `payments`, `inventory_transactions`, `repair_history`, `audit_logs`,
`ai_interactions`, `schema_migrations`.

### API bổ sung theo thiết kế dữ liệu

```text
POST   /api/v1/repair-orders/{id}/parts         # dùng phụ tùng (trừ tồn kho, cập nhật tổng phiếu)
GET    /api/v1/repair-orders/{id}/parts
DELETE /api/v1/repair-orders/{id}/parts/{id}    # hoàn phụ tùng về kho
GET    /api/v1/repair-orders/{id}/notes         # ghi chú kỹ thuật (kèm người ghi, thời gian)
POST   /api/v1/repair-orders/{id}/notes

GET    /api/v1/quotes?order_id=&status=         # báo giá theo phiên bản
GET    /api/v1/quotes/{id}
POST   /api/v1/quotes                           # tạo phiên bản báo giá mới
PATCH  /api/v1/quotes/{id}/status               # duyệt/từ chối; duyệt sẽ vô hiệu phiên bản cũ

GET    /api/v1/invoices/{id}/payments           # giao dịch thanh toán
POST   /api/v1/payments                         # ghi nhận thanh toán, server tự tính trạng thái

GET    /api/v1/reports/revenue?days=7           # doanh thu theo ngày
GET    /api/v1/reports/workload                 # tải công việc theo trạng thái phiếu
GET    /api/v1/reports/inventory                # tồn kho, giá trị kho, phụ tùng sắp hết

GET    /api/v1/audit-logs                       # nhật ký hoạt động (Admin/Quản lý)
GET    /api/v1/ai-interactions                  # nhật ký tương tác AI (Admin/Quản lý)
```


## Trang Lịch hẹn

- Thẻ thống kê: tổng lịch hẹn, đang chờ xác nhận, đã xác nhận, đã tiếp nhận.
- Lọc theo trạng thái, lọc theo ngày hẹn và tìm kiếm theo khách hàng, biển số, dịch vụ.
- Bảng hiển thị giờ hẹn, khách hàng kèm số điện thoại, dòng xe/biển số, dịch vụ,
  **phân công** (kỹ thuật viên + nguồn lực) và trạng thái.
- **Tạo/Sửa lịch**: chọn khách hàng, xe của khách (hoặc nhập biển số), dịch vụ, thời gian,
  thời lượng, kỹ thuật viên, nguồn lực và lý do. Form hiển thị lịch làm việc của garage và
  **kiểm tra trùng lịch ngay khi đổi giờ / kỹ thuật viên / nguồn lực**.
- Lịch mới luôn bắt đầu ở trạng thái **Đang chờ** — hệ thống không tự xác nhận. Nút **Xác nhận**
  chỉ thành công khi khung giờ hợp lệ và không trùng phân công; nếu còn cảnh báo chặn, giao diện
  giải thích lý do và cho phép xác nhận có chủ đích (`force`, được ghi nhật ký).
- **Hủy lịch** bắt buộc nhập lý do; lịch đã hủy có thể khôi phục về Đang chờ. Không thể tạo lịch
  mới ở trạng thái Đã hủy hoặc Đã tiếp nhận.
- **Tiếp nhận xe** mở form nhập số km, mức ưu tiên, kỹ thuật viên và ghi chú. Backend tạo phiếu
  trong cùng transaction; nếu lịch đã có phiếu hoặc xe đang có phiếu mở thì **dùng lại đúng phiếu
  đó** (`already_received` / `reused_existing`) thay vì tạo bản ghi trùng.
- Chi tiết lịch hẹn hiển thị cảnh báo trùng kỹ thuật viên/nguồn lực, phiếu tiếp nhận đã tạo và
  các thao tác Sửa, Hủy, Xác nhận, Tiếp nhận.

### API lịch hẹn

```text
GET   /api/v1/appointments                    # ?status=, ?date=, ?q=, ?technician=, ?resource_id=
GET   /api/v1/appointments/rules              # giờ/ngày làm việc, nguồn lực, kỹ thuật viên
GET   /api/v1/appointments/conflicts          # ?at=&duration_min=&technician=&resource_id=&exclude_id=
POST  /api/v1/appointments
GET   /api/v1/appointments/{id}
PATCH /api/v1/appointments/{id}
POST  /api/v1/appointments/{id}/confirm       # ?force=true khi còn cảnh báo chặn
POST  /api/v1/appointments/{id}/cancel        # body: {reason}
PATCH /api/v1/appointments/{id}/status        # không nhận Đã tiếp nhận
POST  /api/v1/appointments/{id}/receive       # body: {km_in, priority, technician, note}
```

## Trang Khách hàng

- Thẻ thống kê: tổng khách hàng, xe đang quản lý, khách có lịch hẹn, doanh thu tích lũy.
- Tìm kiếm tức thì theo **tên, số điện thoại, email, địa chỉ, biển số và VIN**.
- Lọc theo nhóm: tất cả, có lịch hẹn, nhiều xe, sắp đến hạn bảo dưỡng.
- Bảng hiển thị liên hệ, số xe kèm biển số, **lần sửa gần nhất cùng số km gần nhất** và tổng chi tiêu.
- Hồ sơ khách hàng (ngăn kéo bên phải): sửa thông tin liên hệ, **quản lý nhiều xe** của khách,
  thêm xe mới (kèm VIN), xem **toàn bộ lịch sử sửa chữa**, ghi chú kỹ thuật gần đây và tóm tắt AI.
- **Chống trùng lặp**: khi thêm khách hàng trùng số điện thoại/email, hệ thống hiển thị danh sách
  hồ sơ khả nghi để chọn **Dùng hồ sơ này** hoặc **Vẫn tạo hồ sơ mới**. Khi thêm xe trùng biển số/VIN,
  hệ thống cho phép **Dùng xe này** (nếu cùng chủ) hoặc **Liên kết xe về khách này** (có xác nhận
  chuyển chủ) — tránh tạo bản ghi trùng và luôn gắn đúng bản ghi hiện có.

### API khách hàng & tra cứu

```text
GET   /api/v1/customers?q=&page=&page_size=   # q: tên, SĐT, email, địa chỉ, biển số, VIN
POST  /api/v1/customers                       # thêm ?allow_duplicate=true để bỏ qua cảnh báo trùng
GET   /api/v1/customers/{id}                  # hồ sơ + xe + lịch sử + ghi chú + số km gần nhất
PATCH /api/v1/customers/{id}
GET   /api/v1/customers/duplicates?phone=&email=&name=&plate=&vin=
POST  /api/v1/customers/{id}/vehicles         # thêm ?reuse_existing=true để dùng lại xe đã có
POST  /api/v1/customers/{id}/vehicles/link    # {"vehicle_id": 12, "move": true, "note": "..."}
GET   /api/v1/lookup?plate=&vin=&phone=&name= # tra cứu nhanh khách hàng + xe
```

## Trang Xe

- KPI tổng xe, xe đang sửa, xe có lịch sử và xe chưa từng vào xưởng.
- Tìm kiếm theo biển số, **VIN**, hãng xe, dòng xe, chủ xe; lọc theo tình trạng.
- Bảng hiển thị lần sửa gần nhất kèm **số km gần nhất** và số lần vào xưởng.
- Hồ sơ xe gồm chủ xe, thông tin xe, **lịch sử sửa chữa đầy đủ** (kèm mã phiếu, số km, ghi chú),
  **ghi chú kỹ thuật** và tổng chi tiêu.
- Thêm xe mới kèm **số VIN**; nếu biển số/VIN đã có, hệ thống cảnh báo và cho phép
  **dùng lại xe có sẵn** hoặc **liên kết xe về khách hàng đang mở** (có xác nhận chuyển chủ).

### API xe

```text
GET   /api/v1/vehicles?q=                     # q tìm biển số, VIN, hãng, dòng, chủ xe
GET   /api/v1/vehicles/{id}                   # chi tiết + lịch sử + ghi chú kỹ thuật
GET   /api/v1/vehicles/{id}/repairs           # toàn bộ lịch sử sửa chữa (phân trang)
GET   /api/v1/vehicles/{plate}/history        # lịch sử theo biển số
POST  /api/v1/vehicles?customer_id={id}       # thêm ?reuse_existing=true để dùng lại xe đã có
PATCH /api/v1/vehicles/{id}
POST  /api/v1/vehicles/{id}/link?customer_id={id}   # liên kết/chuyển chủ (move=true)
```

## Trang Xe của tôi

Tài khoản vai trò **Khách hàng** có menu riêng **Xe của tôi**. Trang chỉ gọi dữ liệu thuộc hồ sơ khách hàng đang đăng nhập, hiển thị xe, lịch sử sửa chữa, phiếu đang xử lý và tổng chi tiêu.

```text
GET /api/v1/my-vehicles
```

## Trang Phiếu sửa chữa

Phiếu sửa chữa dùng **máy trạng thái có kiểm soát**: mỗi lần chuyển bước đều được kiểm tra
điều kiện nghiệp vụ, phân quyền và ghi vào lịch sử không thể sửa/xóa.

| Mã | Nhãn hiển thị | Bước |
| --- | --- | --- |
| `RECEIVED` | Tiếp nhận | 1 |
| `INSPECTING` | Đang kiểm tra | 2 |
| `QUOTED` | Đã báo giá | 3 |
| `APPROVED` | Đã duyệt | 4 |
| `IN_PROGRESS` | Đang sửa | 5 |
| `WAITING_FOR_PARTS` | Chờ phụ tùng | 5 (nhánh) |
| `ON_HOLD` | Tạm dừng | 5 (nhánh) |
| `COMPLETED` | Hoàn thành | 6 |
| `DELIVERED` | Đã bàn giao | 7 |
| `CANCELLED` | Đã hủy | kết thúc |

**Luồng chính:** `RECEIVED → INSPECTING → QUOTED → APPROVED → IN_PROGRESS → COMPLETED → DELIVERED`.

**Nhánh hợp lệ:** `IN_PROGRESS ↔ WAITING_FOR_PARTS`, `ON_HOLD` có thể quay lại các bước đang
xử lý, `CANCELLED` kết thúc phiếu. API trả cả `status` (nhãn tiếng Việt) và `status_code`
(mã chuẩn); dữ liệu cũ chỉ có nhãn vẫn được quy đổi tự động.

**Điều kiện trước khi chuyển bước**

- **Sang kiểm tra:** phải có số km tiếp nhận, tình trạng ban đầu, yêu cầu khách hàng và kỹ thuật viên.
- **Sang báo giá:** có ghi chú kiểm tra kỹ thuật và báo giá hợp lệ (có hạng mục, tổng tiền > 0).
- **Duyệt:** báo giá phải có hạng mục, tổng tiền > 0; chỉ **Admin/Quản lý** được duyệt.
  Duyệt báo giá tự chuyển phiếu sang `APPROVED` nếu phiếu đang `QUOTED`.
- **Sang đang sửa/chờ phụ tùng/hoàn thành:** báo giá của phiếu đã được duyệt.
- **Hoàn thành:** có kỹ thuật viên, ít nhất một hạng mục hoặc phụ tùng, ghi chú kiểm tra và
  báo giá đã duyệt; server ghi lịch sử sửa chữa của xe trong cùng transaction.
- **Bàn giao:** có hóa đơn của phiếu và hóa đơn đã thanh toán đầy đủ; chỉ **Admin/Quản lý** được xác nhận.
- **Hủy:** bắt buộc nhập lý do, không còn hóa đơn chưa hủy; chỉ **Admin/Quản lý** được hủy.
- **Chặn nhảy cóc:** ví dụ `RECEIVED → DELIVERED` trả `400` kèm danh sách điều kiện còn thiếu.

**Giao diện**

- Danh sách phiếu với bộ lọc trạng thái, tìm kiếm mã phiếu/biển số/kỹ thuật viên và thẻ thống kê.
- Ngăn chi tiết bên phải có thanh tiến trình 7 bước, vùng chuyển trạng thái chỉ hiện các bước hợp lệ
  kèm lý do bị khóa, form tiếp nhận/kỹ thuật, hạng mục, phụ tùng, báo giá và lịch sử trạng thái.
- Phiếu đã hoàn thành/đã bàn giao/đã hủy không cho sửa nội dung; nút nhạy cảm chỉ hiện với vai trò phù hợp.

### Dịch vụ, phụ tùng và tồn kho

- Danh mục dịch vụ và phụ tùng hỗ trợ CRUD, tìm kiếm, lọc, phân trang, bật/tắt mềm; phụ tùng
  quản lý mã, giá nhập/giá bán, đơn vị, nhà cung cấp, tồn và ngưỡng cảnh báo.
- Xuất phụ tùng theo phiếu tạo dòng sử dụng và trừ kho trong cùng transaction; hoàn/xóa dòng sử dụng
  tạo giao dịch hoàn kho. Tồn kho không được âm.
- Mọi thao tác nhập/xuất/hoàn kho được ghi trong `inventory_transactions`. Client gửi
  `Idempotency-Key` để request retry hoặc nhấn nút nhiều lần không tạo giao dịch thứ hai.
- Cảnh báo tồn thấp khi `stock <= min_stock`; không cho cập nhật tồn trực tiếp qua form chỉnh sửa.

### Báo giá, hóa đơn và thanh toán

- Báo giá lưu snapshot tiền công/phụ tùng, số lượng, chiết khấu, thuế, tổng tiền và thời hạn hiệu lực.
  Trạng thái gồm `Chờ duyệt`, `Đã duyệt`, `Từ chối`, `Hết hiệu lực`.
- Hóa đơn chỉ được lập từ báo giá đã duyệt còn hiệu lực; backend sao chép chi tiết hạng mục và tự
  tính/giữ tổng tiền, số đã thu và số còn phải trả.
- Một hóa đơn nhận nhiều lần thanh toán. Số tiền phải lớn hơn 0, không vượt số còn lại; mã tham chiếu
  và `Idempotency-Key` chống ghi nhận trùng giao dịch.
- AI chỉ tạo bản nháp giải thích/báo giá; không có quyền quyết định giá cuối cùng, thuế, hóa đơn hoặc
  trạng thái thanh toán.

### AI tra cứu hóa đơn và công nợ

- Endpoint `POST /api/v1/ai/invoices/query` nhận duy nhất câu hỏi; danh tính và quyền luôn lấy từ
  Bearer token. Client không thể gửi role, user ID, SQL hoặc số tiền làm dữ liệu nguồn.
- Backend phân quyền riêng bằng `invoice.view`, `invoice.view_amount`, `invoice.view_debt`,
  `invoice.view_all`, `invoice.calculate`. Khách hàng không có `invoice.view_all` nên chỉ thấy hóa
  đơn thuộc hồ sơ của mình. Admin, Quản lý và Thu ngân được cấp đủ quyền theo luồng hiện tại.
- Các hàm giới hạn nằm tại `backend/invoice_query.py`: `get_unpaid_invoices`, `get_paid_invoices`,
  `get_partially_paid_invoices`, `get_invoice_details`, `get_invoice_payment_summary` và
  `get_outstanding_debt_summary`. Không có công cụ SQL tùy ý cho mô hình.
- Số đã thu được cộng từ `payments.status='completed'`; giao dịch `failed`, `voided`, `refunded`
  không được tính. Nếu số cache/trạng thái hóa đơn không khớp giao dịch thực, AI từ chối công bố số
  liệu và yêu cầu kiểm tra thay vì tự đoán.

### API phiếu sửa chữa

```text
GET    /api/v1/repair-orders                 # danh sách, ?status= nhận mã hoặc nhãn, ?q=, ?page=&page_size=
POST   /api/v1/repair-orders                 # tạo phiếu, tự sinh mã nếu để trống
GET    /api/v1/repair-orders/workflow        # định nghĩa trạng thái + các cạnh hợp lệ
GET    /api/v1/repair-orders/{id}            # chi tiết + hạng mục + báo giá + lịch sử + bước được phép
PATCH  /api/v1/repair-orders/{id}            # cập nhật thông tin; đổi trạng thái cũng đi qua workflow
POST   /api/v1/repair-orders/{id}/transition # {"status_code":"INSPECTING","note":"..."} chuyển có kiểm tra
GET    /api/v1/repair-orders/{id}/history    # lịch sử trạng thái bất biến, kèm người/thời gian/lý do
POST   /api/v1/repair-orders/{id}/items      # thêm hạng mục, server tính lại tổng
DELETE /api/v1/repair-orders/{id}/items/{item_id}
POST   /api/v1/repair-orders/{id}/parts      # dùng phụ tùng, trừ kho
GET    /api/v1/repair-orders/{id}/notes      # ghi chú kỹ thuật
```
