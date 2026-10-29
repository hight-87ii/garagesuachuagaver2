# Thiết kế API — GarageAI

Tài liệu mô tả hợp đồng API của backend: phiên bản, xác thực, quy ước chung, danh mục
endpoint và các quy tắc bảo mật. Đặc tả máy đọc được luôn có tại `/openapi.json`
(Swagger UI: `/docs`).

## 1. Phiên bản & địa chỉ

| Mục | Giá trị |
| --- | --- |
| Base URL (dev) | `http://127.0.0.1:8014` |
| Tiền tố API | `/api/v1` |
| Tương thích ngược | `/api/...` được middleware viết lại thành `/api/v1/...` (không có trong OpenAPI) |
| Kiểm tra sức khỏe | `GET /health` |

Quy ước: mọi thay đổi phá vỡ tương thích sẽ phát hành `/api/v2`; trong `v1` chỉ thêm
trường mới (client bỏ qua trường lạ).

## 2. Xác thực & phân quyền

- Đăng nhập: `POST /api/v1/auth/login` → `access_token` (HMAC, hạn 12 giờ).
- Gửi kèm: `Authorization: Bearer <token>`.
- Token sai/hết hạn → `401`; thiếu quyền hoặc không sở hữu bản ghi → `403`.

| Vai trò | Quyền chính |
| --- | --- |
| Admin | Toàn quyền (`*`) |
| Quản lý | dashboard, appointments, repair_orders, customers, vehicles, services, inventory, invoices, staff |
| Lễ tân | dashboard, appointments, customers, vehicles, services |
| Kỹ thuật viên | dashboard, repair_orders, vehicles, inventory |
| Thu ngân | dashboard, customers, invoices |
| Khách hàng | dashboard, appointments, my_vehicles |

Quyền được kiểm tra **ở server** bằng dependency `require_permission(...)`; frontend chỉ
ẩn/hiện giao diện, không phải lớp bảo vệ.

## 3. Quy ước chung

### 3.1 Mã trạng thái

| Mã | Ý nghĩa |
| --- | --- |
| `200` | Đọc/cập nhật thành công |
| `201` | Tạo mới thành công |
| `400` | Vi phạm nghiệp vụ (ví dụ: thanh toán vượt số còn phải thu) |
| `401` | Chưa đăng nhập / token không hợp lệ |
| `403` | Thiếu quyền hoặc không sở hữu bản ghi |
| `404` | Không tìm thấy tài nguyên |
| `409` | Xung đột dữ liệu (trùng biển số, VIN, khách hàng, mã phụ tùng, email) |
| `422` | Dữ liệu đầu vào không hợp lệ (kiểu, độ dài, trường lạ) |
| `500` | Lỗi hệ thống (không lộ chi tiết nội bộ) |

### 3.2 Cấu trúc lỗi thống nhất

```json
{
  "error": {
    "code": "validation_error",
    "message": "Dữ liệu gửi lên không hợp lệ",
    "details": [
      { "type": "string_too_short", "loc": ["body", "phone"], "msg": "..." }
    ]
  },
  "detail": "Dữ liệu gửi lên không hợp lệ"
}
```

`detail` được giữ để tương thích với client cũ; client mới nên đọc `error.code`.

### 3.3 Phân trang, tìm kiếm, lọc

Mọi endpoint danh sách trả về:

```json
{ "items": [], "total": 0, "page": 1, "page_size": 50, "pages": 0 }
```

- `page` ≥ 1 (mặc định 1); `page_size` 1–200 (mặc định 50) → vượt giới hạn trả `422`.
- `q` tìm kiếm chuỗi (không phân biệt hoa thường với ASCII).
- Bộ lọc riêng theo module: `status`, `category`, `date`, `low_stock`, `order_id`,
  `task_type`...

### 3.4 Thời gian & tiền tệ

- Thời gian lưu **UTC** dạng `YYYY-MM-DDTHH:MM:SSZ`; API danh sách/chi tiết trả về
  chuỗi đã đổi sang **giờ Việt Nam (UTC+7)** cho các trường hiển thị.
- Tiền là **số nguyên đồng** (`int`), không dùng số thực. Server tính bằng `Decimal`
  rồi làm tròn về đồng.

### 3.5 Chống trùng lặp & liên kết bản ghi

- **Khách hàng**: `POST /customers` kiểm tra trùng theo SĐT (chuẩn hóa dữ số) và email.
  Nếu có hồ sơ khả nghi, API trả `409` kèm `error.details.customers` để client chọn
  "dùng hồ sơ cũ" (bỏ qua tạo mới) hoặc gửi lại với `?allow_duplicate=true`.
- **Xe**: `POST /customers/{id}/vehicles` kiểm tra trùng theo biển số chuẩn hóa và VIN.
  - Cùng khách hàng + `?reuse_existing=true` → trả về bản ghi hiện có với `reused: true`.
  - Khác khách hàng → `409` kèm `details.suggest = "link_vehicle"`; muốn gắn về khách mới
    phải xác nhận bằng `/customers/{id}/vehicles/link` hoặc `/vehicles/{id}/link` với
    `move=true` (ghi audit `vehicle.link`).
- **Lịch sử sửa chữa**: khi phiếu chuyển sang `Hoàn thành`, server ghi **một** dòng
  `repair_history` (chống ghi trùng bằng chỉ mục duy nhất `ux_repair_history_order`),
  đồng thời cập nhật số km mới nhất của xe. Dữ liệu cũ được bổ sung tự động khi đọc
  (`GET /vehicles/{id}`, `/vehicles/{id}/repairs`, `/customers/{id}`).

### 3.6 Lịch hẹn & điều phối

- **Không tự xác nhận:** lịch mới luôn ở `Đang chờ`. `POST /appointments` từ chối trạng thái
  `Đã hủy` / `Đã tiếp nhận` (400). Xác nhận đi qua `/confirm` (hoặc tạo với
  `status="Đã xác nhận"`) và phải vượt qua kiểm tra quy tắc.
- **Kiểm tra lịch làm việc:** ngày/giờ làm việc đọc từ `GARAGE_WORKING_DAYS` (ISO-8601),
  `GARAGE_WORKING_START`, `GARAGE_WORKING_END` (giờ Việt Nam). Ngoài giờ hoặc ngày nghỉ là
  cảnh báo mức `blocking`.
- **Xung đột phân công:** trùng **kỹ thuật viên** (lịch còn hiệu lực; kỹ thuật viên đang có
  phiếu mở là cảnh báo) và trùng **nguồn lực** (khoang sửa, cầu nâng…). Phần nguồn lực chỉ bật
  khi bảng `resources` có ít nhất một nguồn lực `active = 1`.
- `GET /appointments/conflicts` trả `{ok, blocking, warnings, message}` để giao diện kiểm tra
  trước khi lưu. Xác nhận còn `blocking` → `409` mã `appointment_conflict` kèm
  `error.details.blocking`, `warnings`, `suggest`. `?force=true` cho phép bỏ qua nhưng ghi audit
  `appointment.confirm` với `forced: true`.
- **Hủy lịch** bắt buộc `reason` (≥ 2 ký tự), lưu `cancelled_at`, `cancel_reason`; lịch đã tiếp
  nhận không hủy/sửa được (xử lý trên phiếu sửa chữa). Có thể khôi phục lịch đã hủy về `Đang chờ`.
- `PATCH /appointments/{id}/status` **không nhận** `Đã tiếp nhận` (400, hướng dẫn dùng `/receive`).
- **Tiếp nhận không trùng:** `POST /appointments/{id}/receive` idempotent — lịch đã có phiếu thì
  trả lại đúng phiếu (`already_received`); xe đang có phiếu mở thì dùng lại (`reused_existing`);
  chỉ tạo mới khi chưa có, tất cả trong một transaction. Nhiều lịch của cùng một xe được phép
  trỏ về cùng một phiếu (migration `006`), nhờ vậy không sinh phiếu trùng.

### 3.7 Quy trình trạng thái phiếu sửa chữa

Phiếu trả về **cả hai** trường: `status` (nhãn tiếng Việt, tương thích client cũ) và
`status_code` (mã chuẩn). Khi ghi, server chấp nhận mã hoặc nhãn cũ và tự chuẩn hóa.

| Mã | Nhãn | Bước | Ghi chú |
| --- | --- | --- | --- |
| `RECEIVED` | Tiếp nhận | 1 | Xe đã vào xưởng |
| `INSPECTING` | Đang kiểm tra | 2 | Nhãn cũ `Kiểm tra` được quy đổi |
| `QUOTED` | Đã báo giá | 3 | Đã có báo giá hợp lệ |
| `APPROVED` | Đã duyệt | 4 | Báo giá được Admin/Quản lý duyệt |
| `IN_PROGRESS` | Đang sửa | 5 | Đang thi công |
| `WAITING_FOR_PARTS` | Chờ phụ tùng | 5 | Nhánh tạm dừng |
| `ON_HOLD` | Tạm dừng | 5 | Nhánh tạm dừng, cần lý do |
| `COMPLETED` | Hoàn thành | 6 | Đã ghi lịch sử xe |
| `DELIVERED` | Đã bàn giao | 7 | Kết thúc, hóa đơn đã thanh toán |
| `CANCELLED` | Đã hủy | — | Kết thúc, cần lý do |

Các cạnh hợp lệ (không cho nhảy cóc):

```text
RECEIVED          → INSPECTING | CANCELLED
INSPECTING        → QUOTED | ON_HOLD | CANCELLED
QUOTED            → INSPECTING | APPROVED | ON_HOLD | CANCELLED
APPROVED          → IN_PROGRESS | ON_HOLD | CANCELLED
IN_PROGRESS       → WAITING_FOR_PARTS | ON_HOLD | COMPLETED | CANCELLED
WAITING_FOR_PARTS → IN_PROGRESS | ON_HOLD | CANCELLED
ON_HOLD           → INSPECTING | QUOTED | APPROVED | IN_PROGRESS | WAITING_FOR_PARTS | CANCELLED
COMPLETED         → DELIVERED
DELIVERED         → (kết thúc)
CANCELLED         → (kết thúc)
```

Điều kiện nghiệp vụ khi chuyển bước:

- **INSPECTING:** có `km_in`, `initial_condition`, `customer_request`, `technician`.
- **QUOTED:** thêm `inspection_notes` và báo giá có hạng mục, `total > 0`.
- **APPROVED:** báo giá đã duyệt; nếu còn báo giá mới hơn chưa duyệt thì bị chặn.
  Chỉ **Admin/Quản lý** được duyệt báo giá; duyệt xong phiếu `QUOTED` tự sang `APPROVED`.
- **IN_PROGRESS / WAITING_FOR_PARTS / COMPLETED:** báo giá của phiếu đã duyệt.
- **COMPLETED:** có kỹ thuật viên, ít nhất một hạng mục/phụ tùng, ghi chú kiểm tra và báo giá
  đã duyệt. Server ghi `repair_history` của xe trong cùng transaction.
- **DELIVERED:** có hóa đơn của phiếu và hóa đơn đã thanh toán đầy đủ. Chỉ **Admin/Quản lý**
  được xác nhận bàn giao.
- **CANCELLED:** bắt buộc `note` ≥ 2 ký tự; không còn hóa đơn chưa hủy. Chỉ **Admin/Quản lý**
  được hủy phiếu.
- Vi phạm cạnh hoặc điều kiện trả `400` với `error.details.blockers` gồm `code` và `message`.

`GET /repair-orders/{id}` trả thêm `allowed_transitions` (bước được phép, `enabled`, lý do khóa)
và `history`. `PATCH /repair-orders/{id}` khi có `status`/`status_code` cũng đi qua đúng máy
trạng thái; endpoint chuyên dụng là `POST /repair-orders/{id}/transition`. Lịch sử trạng thái
được ghi bất biến bằng trigger CSDL (không sửa/xóa).

## 4. Danh mục endpoint

### 4.1 Xác thực & phân quyền

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | Đăng ký tài khoản Lễ tân |
| POST | `/api/v1/auth/login` | Đăng nhập, trả token + hồ sơ công khai |
| GET | `/api/v1/auth/me` | Hồ sơ người dùng hiện tại + quyền |
| POST | `/api/v1/auth/password` | Đổi mật khẩu (kiểm tra mật khẩu hiện tại) |
| GET | `/api/v1/rbac/roles` | Ma trận vai trò → quyền (Admin/Quản lý) |

### 4.2 Khách hàng & phương tiện

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| GET | `/api/v1/customers` | Danh sách + `q` (tên, SĐT, email, địa chỉ, biển số, VIN), phân trang |
| POST | `/api/v1/customers` | Tạo khách hàng; `?allow_duplicate=true` để bỏ qua cảnh báo trùng |
| GET | `/api/v1/customers/{id}` | Chi tiết: xe, lịch sử, ghi chú kỹ thuật, lần sửa gần nhất, số km, tổng chi tiêu |
| PATCH | `/api/v1/customers/{id}` | Cập nhật hồ sơ |
| GET | `/api/v1/customers/duplicates` | Kiểm tra trùng theo `phone`, `email`, `name`, `plate`, `vin` |
| POST | `/api/v1/customers/{id}/vehicles` | Thêm xe cho khách; `?reuse_existing=true` để dùng lại xe đã có |
| POST | `/api/v1/customers/{id}/vehicles/link` | Liên kết xe đã có với khách (`vehicle_id`, `move`, `note`) |
| GET | `/api/v1/lookup` | Tra cứu nhanh khách hàng + xe (`q`, `phone`, `email`, `name`, `plate`, `vin`) |
| GET | `/api/v1/vehicles` | Danh sách xe + `q`; kèm `last_mileage`, `last_service`, `last_note` |
| POST | `/api/v1/vehicles?customer_id=` | Tạo xe (biển số chuẩn hóa, VIN duy nhất) |
| GET | `/api/v1/vehicles/{id}` | Chi tiết xe + lịch sử + ghi chú kỹ thuật |
| PATCH | `/api/v1/vehicles/{id}` | Cập nhật xe |
| POST | `/api/v1/vehicles/{id}/link?customer_id=` | Liên kết/chuyển xe sang khách khác (`move=true` khi khác chủ) |
| GET | `/api/v1/vehicles/{plate}/history` | Lịch sử sửa chữa theo biển số |
| GET | `/api/v1/vehicles/{id}/repairs` | Toàn bộ lịch sử sửa chữa theo ID xe (kèm mã phiếu, có phân trang) |
| GET | `/api/v1/my-vehicles` | Cổng khách hàng: xe + lịch sử của chính mình |

### 4.3 Lịch hẹn

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| GET | `/api/v1/appointments` | `status`, `date` (giờ VN), `q`, `technician`, `resource_id`; khách hàng chỉ thấy lịch của mình |
| POST | `/api/v1/appointments` | Tạo lịch hẹn (tự liên kết xe/khách nếu biển số đã có); luôn `Đang chờ` trừ khi xác nhận hợp lệ |
| GET | `/api/v1/appointments/rules` | Ngày/giờ làm việc, nguồn lực đang hoạt động, kỹ thuật viên |
| GET | `/api/v1/appointments/conflicts` | Kiểm tra trước: `at`, `duration_min`, `technician`, `resource_id`, `exclude_id` |
| GET | `/api/v1/appointments/{id}` | Chi tiết + cảnh báo trùng lịch còn hiệu lực (kiểm tra chủ sở hữu) |
| PATCH | `/api/v1/appointments/{id}` | Sửa lịch (không áp dụng cho lịch đã hủy/đã tiếp nhận) |
| POST | `/api/v1/appointments/{id}/confirm` | Xác nhận; `?force=true` để bỏ qua cảnh báo chặn (ghi audit) |
| POST | `/api/v1/appointments/{id}/cancel` | Hủy kèm `reason` (≥ 2 ký tự) |
| PATCH | `/api/v1/appointments/{id}/status` | Đổi trạng thái (không nhận `Đã tiếp nhận`) |
| POST | `/api/v1/appointments/{id}/receive` | Chuyển thành phiếu tiếp nhận, dùng lại phiếu mở của xe nếu có |

### 4.4 Dịch vụ, phụ tùng & kho

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| GET | `/api/v1/services` | `q`, `category` |
| POST | `/api/v1/services` | Tạo dịch vụ |
| PATCH | `/api/v1/services/{id}` | Cập nhật (gồm `active`) |
| GET | `/api/v1/parts` | `q`, `category`, `low_stock` |
| POST | `/api/v1/parts` | Tạo phụ tùng (mã duy nhất) |
| PATCH | `/api/v1/parts/{id}` | Cập nhật phụ tùng |
| POST | `/api/v1/parts/{id}/stock` | Nhập thêm tồn kho |

`PATCH /parts/{id}` chỉ cập nhật mã, thông tin, giá, ngưỡng cảnh báo và trạng thái; không được
ghi đè trực tiếp `stock`. Nhập kho phải đi qua endpoint giao dịch. Xuất phụ tùng theo phiếu
kiểm tra `stock >= quantity` trong cùng transaction với việc tạo dòng sử dụng, nên không thể
tạo tồn kho âm.

Client gửi header `Idempotency-Key` duy nhất cho mỗi thao tác nhập/xuất/hoàn kho. Server lưu
khóa trong `inventory_transactions`; gửi lại cùng khóa và cùng payload trả lại kết quả cũ,
không trừ kho lần hai; dùng khóa cho payload khác trả `409`. Hoàn kho khi xóa/điều chỉnh dòng
phụ tùng tạo giao dịch `REVERSE`, và thao tác hoàn lặp lại là no-op. `GET /parts` hỗ trợ
`q`, `category`, `low_stock`, `page`, `page_size`; tồn thấp được xác định bởi `stock <= min_stock`.

### 4.4.1 Báo giá, hóa đơn và thanh toán

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| GET | `/api/v1/quotes` | Danh sách báo giá, lọc `order_id`, `status`, phân trang |
| POST | `/api/v1/quotes` | Tạo báo giá; server tính dòng tiền, chiết khấu, thuế và thời hạn |
| GET | `/api/v1/quotes/{id}` | Chi tiết báo giá và các dòng snapshot |
| PATCH | `/api/v1/quotes/{id}/status` | Duyệt/từ chối; chỉ Admin/Quản lý được duyệt |
| GET | `/api/v1/invoices/candidates` | Báo giá đã duyệt, còn hiệu lực, chưa lập hóa đơn |
| GET | `/api/v1/invoices` | Danh sách hóa đơn, tổng/đã thu/còn lại/trạng thái |
| POST | `/api/v1/invoices` | Lập hóa đơn từ báo giá đã duyệt; server tạo snapshot hạng mục |
| GET | `/api/v1/invoices/{id}` | Chi tiết hóa đơn, dòng hạng mục và các lần thanh toán |
| GET | `/api/v1/invoices/{id}/payments` | Các lần thanh toán của hóa đơn |
| POST | `/api/v1/payments` | Ghi nhận một phần/toàn bộ thanh toán |

Báo giá hết hạn tự chuyển thành `Hết hiệu lực` khi được đọc/kiểm tra. Hóa đơn không nhận tổng tiền,
thuế, chiết khấu, trạng thái hoặc số đã thanh toán từ client; tất cả lấy từ báo giá và giao dịch server.
Thanh toán hỗ trợ nhiều lần, kiểm tra `0 < amount <= remaining`, chống trùng `reference_code` trong
một hóa đơn và hỗ trợ header `Idempotency-Key`. Gửi lại cùng khóa trả kết quả cũ; dùng khóa cho hóa
đơn khác trả `409`.

### 4.5 Phiếu sửa chữa, báo giá

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| GET | `/api/v1/repair-orders` | `status` (mã hoặc nhãn), `q` |
| POST | `/api/v1/repair-orders` | Tạo phiếu, tự sinh mã `PSC-...` |
| GET | `/api/v1/repair-orders/workflow` | Danh mục trạng thái, bước, các cạnh hợp lệ và hành động nhạy cảm |
| GET | `/api/v1/repair-orders/{id}` | Chi tiết + hạng mục, phụ tùng, ghi chú, báo giá, `allowed_transitions`, `history` |
| PATCH | `/api/v1/repair-orders/{id}` | Thông tin/trạng thái; đổi trạng thái đi qua máy trạng thái và kiểm tra điều kiện |
| POST | `/api/v1/repair-orders/{id}/transition` | `{"status_code":"...","note":"..."}`; `400` kèm `blockers` nếu chưa đủ điều kiện |
| GET | `/api/v1/repair-orders/{id}/history` | Lịch sử trạng thái bất biến (người đổi, thời gian, lý do) |
| POST | `/api/v1/repair-orders/{id}/items` | Thêm hạng mục (server tính `line_total`, `order_total`) |
| DELETE | `/api/v1/repair-orders/{id}/items/{item_id}` | Xóa hạng mục |
| GET/POST | `/api/v1/repair-orders/{id}/parts` | Phụ tùng đã dùng (trừ/hoàn tồn kho) |
| DELETE | `/api/v1/repair-orders/{id}/parts/{part_use_id}` | Hoàn phụ tùng về kho |
| GET/POST | `/api/v1/repair-orders/{id}/notes` | Ghi chú kỹ thuật (kèm người ghi) |
| GET | `/api/v1/quotes` | `order_id`, `status` |
| POST | `/api/v1/quotes` | Tạo phiên bản báo giá (server tính subtotal/thuế/tổng) |
| GET | `/api/v1/quotes/{id}` | Chi tiết báo giá |
| PATCH | `/api/v1/quotes/{id}/status` | Duyệt/từ chối; duyệt cần Admin/Quản lý, báo giá có hạng mục và tổng > 0 |

### 4.6 Hóa đơn & thanh toán

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| GET | `/api/v1/invoices` | `status`, `q` |
| POST | `/api/v1/invoices` | Tạo hóa đơn từ phiếu sửa chữa |
| PATCH | `/api/v1/invoices/{id}/status` | Hủy/đánh dấu đã thanh toán (đồng bộ `paid_amount`) |
| GET | `/api/v1/invoices/{id}/payments` | Danh sách giao dịch |
| POST | `/api/v1/payments` | Ghi nhận thanh toán |

### 4.7 Báo cáo, AI, kiểm toán

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| GET | `/api/v1/dashboard` | Số liệu tổng quan + lịch hẹn/phiếu gần nhất (alias: `/reports/dashboard`) |
| GET | `/api/v1/reports/revenue?days=7` | Doanh thu theo ngày |
| GET | `/api/v1/reports/workload` | Số phiếu theo trạng thái |
| GET | `/api/v1/reports/inventory` | Tồn kho, giá trị kho, phụ tùng sắp hết |
| POST | `/api/v1/ai/generate` | Sinh bản nháp AI (`summary`/`explain`/`estimate`) |
| GET | `/api/v1/audit-logs` | Nhật ký hoạt động (Admin/Quản lý) |
| GET | `/api/v1/ai-interactions` | Nhật ký tương tác AI (Admin/Quản lý) |

## 5. Quy tắc bảo mật

1. **RBAC ở server**: mọi endpoint đều có dependency quyền; không tin frontend.
2. **Chống IDOR**: `core/access.py` kiểm tra chủ sở hữu bản ghi với vai trò Khách hàng;
   danh sách lịch hẹn của khách hàng bị giới hạn theo hồ sơ của chính họ.
3. **Tiền do server quyết định**:
   - `total` phiếu sửa chữa = tổng hạng mục + phụ tùng (client gửi `total` → `422`).
   - Hóa đơn: `subtotal/tax/total/paid_amount/status` không nhận từ client; thuế lấy từ
     cấu hình server (`DEFAULT_TAX_RATE`).
   - Thanh toán: `amount` tùy chọn (mặc định = số còn lại), phải > 0 và ≤ số còn phải thu;
     trạng thái hóa đơn do server suy ra.
4. **Không lộ dữ liệu nhạy cảm**: response không chứa `password_hash`; nhật ký kiểm toán
   che các khóa `password/token/secret/...`; log truy cập chỉ ghi method, path, status,
   thời gian — không ghi body hay header.
5. **Kiểm tra đầu vào**: Pydantic giới hạn độ dài/kiểu/giá trị; trường lạ bị từ chối
   (`extra="forbid"`).
6. **Toàn vẹn dữ liệu**: ghi nhiều bảng trong một transaction; trigger chặn xóa cứng
   hóa đơn/lịch sử.

## 6. Ví dụ

### Đăng nhập và gọi danh sách có phân trang

```bash
curl -X POST http://127.0.0.1:8014/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@garage.vn","password":"Admin@123"}'

curl "http://127.0.0.1:8014/api/v1/customers?q=Nguy%E1%BB%85n&page=1&page_size=10" \
  -H "Authorization: Bearer <access_token>"
```

### Tạo hóa đơn và ghi nhận thanh toán

```bash
curl -X POST http://127.0.0.1:8014/api/v1/invoices \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"repair_order_id": 12}'

curl -X POST http://127.0.0.1:8014/api/v1/payments \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"invoice_id": 3, "method": "Chuyển khoản", "amount": 500000}'
```

`amount` bỏ trống nghĩa là thu hết phần còn lại. Nếu vượt số còn phải thu, API trả `400`.

### Yêu cầu bị từ chối do gửi trường tiền tùy chỉnh

```json
POST /api/v1/invoices
{ "repair_order_id": 12, "total": 1 }

→ 422
{
  "error": {
    "code": "validation_error",
    "message": "Dữ liệu gửi lên không hợp lệ",
    "details": [{ "type": "extra_forbidden", "loc": ["body", "total"], "msg": "Extra inputs are not permitted" }]
  },
  "detail": "Dữ liệu gửi lên không hợp lệ"
}
```

### Phát hiện trùng lặp khách hàng và liên kết bản ghi

```bash
# 1) Tạo khách hàng trùng số điện thoại -> 409 kèm danh sách hồ sơ khả nghi
curl -X POST http://127.0.0.1:8014/api/v1/customers \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"name":"Nguyễn Minh Anh 2","phone":"090 123 4567"}'

# 2) Chấp nhận trùng -> tạo mới
curl -X POST "http://127.0.0.1:8014/api/v1/customers?allow_duplicate=true" \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"name":"Nguyễn Minh Anh 2","phone":"090 123 4567"}'

# 3) Gắn xe đã có vào khách khác (cần xác nhận chuyển chủ)
curl -X POST http://127.0.0.1:8014/api/v1/customers/3/vehicles/link \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"vehicle_id": 12, "move": true, "note": "Khách mua lại xe"}'

# 4) Tra cứu nhanh theo biển số/VIN trước khi nhập liệu
curl "http://127.0.0.1:8014/api/v1/lookup?plate=51H-123.45" \
  -H "Authorization: Bearer <access_token>"
```

Trường `error.details` của `409` luôn cho biết `reason`
(`duplicate_customer` / `duplicate_plate` / `duplicate_vin` /
`vehicle_belongs_to_other_customer`), bản ghi hiện có và gợi ý xử lý (`suggest`).

## 7. Hành vi của AI

- `POST /api/v1/ai/generate` chỉ nhận dữ liệu do client cung cấp (`data`), không tự truy
  vấn thêm; kết quả luôn kèm `is_draft: true` và cần kỹ thuật viên xác nhận.
- Nội dung prompt **không** được lưu; chỉ lưu `prompt_hash`, trạng thái, model và thời gian
  xử lý để kiểm toán.
- Các tác vụ cần tạo sinh gọi Ollama cục bộ; không dùng `OPENAI_API_KEY` hoặc OpenAI từ xa. Một số tác vụ có phản hồi dự phòng an toàn khi mô hình không khả dụng.

## 8. Kiểm thử

```bash
python -m pytest backend/tests -q
```

Bộ test bao phủ: phiên bản API + alias, phân trang, cấu trúc lỗi, RBAC, chống IDOR,
che dữ liệu nhạy cảm, kiểm tra đầu vào, toàn bộ luồng phiếu sửa chữa → báo giá → hóa đơn
→ thanh toán, quy tắc chống sửa tổng tiền, AI an toàn, báo cáo, migration và ràng buộc CSDL,
cùng nhóm kiểm thử khách hàng & xe: tìm theo tên/SĐT/biển số/VIN, phát hiện trùng lặp,
dùng lại/liên kết bản ghi hiện có, và lịch sử sửa chữa sinh ra khi phiếu hoàn thành
(kèm số km, dịch vụ, ghi chú). Nhóm quy trình sửa chữa kiểm tra chặn nhảy cóc, điều kiện
từng bước, phân quyền duyệt/hủy/bàn giao, hóa đơn chưa thanh toán và lịch sử bất biến — 50 test.
