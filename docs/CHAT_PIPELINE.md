# Luồng chat dùng chung

| Trước khi hợp nhất | API hội thoại | API chat cũ | Sau khi hợp nhất |
| --- | --- | --- | --- |
| Lịch sử | Tin nhắn đã lưu, `context_summary`, retry bằng `request_id` | `history` do client gửi | Adapter giữ riêng; chỉ trạng thái do server lưu được dùng để tra tiếp mã phụ tùng. |
| Quyền xe/kho | Kiểm tra chủ hội thoại, xe, tồn kho | Kiểm tra xe, tồn kho; có đường từ chối sớm | `backend/chat_pipeline.py` kiểm tra nguồn và quyền một lần cho cả hai. |
| Intent và dữ liệu | Nhánh thống kê, kho, giá, lịch hẹn, xe, hóa đơn, kỹ thuật | Cùng các nhánh nhưng thứ tự/điều kiện khác | Một thứ tự điều phối chung; cùng các helper truy vấn có tham số. |
| RAG/Ollama/nguồn | Lọc nguồn riêng sau sinh | Lọc nguồn riêng sau sinh | Tra RAG trước rồi gọi Ollama; nếu không có RAG, Ollama vẫn trả lời kiến thức phổ thông với cảnh báo tham khảo, không được nhận là dữ liệu garage. |
| Ghi dữ liệu | Lưu tin, metadata, audit | Chỉ audit | Không đổi: pipeline không lưu hội thoại. |

`answer_chat()` gọi Ollama cục bộ phân tích câu hỏi trước khi truy vấn DB. Chỉ
gửi câu hỏi và câu hỏi trước đó (nếu lịch sử do server lưu), không gửi hồ sơ,
giá hoặc quyền. Kết quả JSON được kiểm tra kiểu/trường/intent trong
`backend/chat_intent.py`; thông số không hiện trong câu gốc bị loại. Nếu Ollama
không sẵn sàng hoặc trả sai JSON, định tuyến cũ vẫn hoạt động. Chỉ dùng gợi ý
đã kiểm tra để chuẩn hóa một từ đồng nghĩa được whitelist ("vỏ bánh" → "lốp"
khi hỏi giá); mô hình không được tự chọn SQL, phân quyền hoặc phê duyệt giá.

Sau đó `answer_chat()` chuẩn bị dữ liệu dưới transaction ngắn, đóng transaction
trước khi truy xuất tài liệu/sinh lời đáp, rồi kiểm tra nguồn và tạo `ChatOutput`.
Các hàm nghiệp vụ truy xuất/dựng nguồn được tái sử dụng; hai endpoint dùng chung
pipeline. Câu hỏi giá có snapshot được duyệt có thể gọi Ollama lần hai để chọn
lời dẫn; mọi giá, mã và giới hạn vẫn do backend ghép nguyên văn. Với RAG/kiến
thức phổ thông, lời đáp cuối tiếp tục qua Ollama hiện có. Không gọi lượt sinh
giá khi thiếu nguồn; số lượt model tăng và có thể tăng thời gian phản hồi.

Payload thương mại gửi cho lượt Ollama cuối có dạng `question`, `intent_analysis`,
`verified_database`, `verified_rag`, `user_claims`, `missing_data` và
`backend_answer`. `verified_database` chỉ chứa mã/tên/đơn vị/giá đã duyệt; không
chứa SQL, `cost_price`, tồn kho hoặc dữ liệu vượt quyền. Backend luôn giữ nguyên
`backend_answer` nếu model không trả đúng định dạng được phép.

Với câu hỏi không khớp intent nghiệp vụ và không tìm được tài liệu RAG, `answer_assistant`
được dùng làm fallback Ollama. Đây là câu trả lời kiến thức phổ thông, không có quyền
khẳng định giá, tồn kho, hồ sơ xe, lịch hẹn hoặc trạng thái garage. Khi có tài liệu RAG,
Ollama chỉ được dùng các trích đoạn đã truy xuất và phải nêu giới hạn nếu nguồn thiếu hoặc
mâu thuẫn.

Lịch sử gửi từ client chỉ hỗ trợ bối cảnh ngôn ngữ, không mang trạng thái
`product_ids` hoặc quyền đã xác minh. Giá/tồn kho được truy vấn lại; giá chưa
được phê duyệt không được trả qua câu hỏi nối tiếp. API hội thoại vẫn ghi tin
nhắn lỗi và giữ nguyên `request_id` để thử lại; retry cùng mã lấy bản trả lời đã
lưu. Khi provider lỗi, API cũ trả `status=error`, API hội thoại giữ tin thất bại
và trả 503 như trước.

Hai API giữ nguyên đường dẫn và cấu trúc response. Không thay đổi dữ liệu thật,
không lập lại chỉ mục RAG. Chưa kiểm chứng giao diện thực tế sau khi triển khai
backend mới; cần sao lưu DB trước khi áp dụng migration giá đã có trong dự án.
