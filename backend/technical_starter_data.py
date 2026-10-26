"""Bài tiếp nhận triệu chứng phổ thông, tham khảo từ nguồn công khai, KHÔNG phải chẩn đoán.

Các bài mẫu được xuất bản để chat demo tra cứu được ngay; reviewed_by=NULL biểu thị
garage CHƯA duyệt. Không ghi đè bản ghi đã được nhân viên sửa/thu hồi.
"""

from .database import transaction
from .technical_documents import index_article_chunks


# title, symptoms (gồm cách gọi tiếng Việt), content, safety, source_name, source_url
ARTICLES = [
    (
        "Tiếng lọc cọc ở gầm khi chạy qua đường xấu",
        "lọc cọc, lộc cộc, cộc cộc, kêu gầm, kêu dưới gầm, đi qua ổ gà, qua gờ giảm tốc",
        "Hãy hỏi tiếng xuất hiện khi qua ổ gà, khi đánh lái hay khi phanh, và ở phía trước hay phía sau. "
        "Tiếng lọc cọc khi qua chỗ xóc có thể liên quan đến hệ thống treo hoặc cơ cấu lái, chẳng hạn liên kết "
        "và khớp gầm; cũng cần loại trừ chi tiết bị lỏng. Kỹ thuật viên kiểm tra xe trực tiếp, "
        "không quyết định thay bộ phận chỉ dựa vào âm thanh.",
        "Nếu xe lệch lái, vô lăng lỏng, rung mạnh hoặc khó kiểm soát, hãy dừng nơi an toàn và gọi cứu hộ.",
        "Firestone Complete Auto Care — Steering & Suspension Repair",
        "https://www.firestonecompleteautocare.com/repair/steering-suspension",
    ),
    (
        "Phanh kêu rít hoặc tiếng nghiến khi đạp phanh",
        "phanh kêu, thắng kêu, kêu rít khi phanh, phanh kêu ken két, tiếng nghiến khi thắng",
        "Hãy hỏi tiếng kêu chỉ xuất hiện khi đạp phanh hay cả lúc thả phanh, ở bánh nào, "
        "có rung bàn đạp hoặc quãng phanh thay đổi không. Má phanh và đĩa phanh là các hạng mục cần kiểm tra, "
        "nhưng tiếng kêu không đủ để xác định phải thay má phanh; cần kiểm tra thực tế trước khi báo giá.",
        "Nếu phanh giảm tác dụng, bàn đạp lún bất thường hoặc tiếng nghiến lớn liên tục, dừng xe an toàn và gọi cứu hộ.",
        "AAA Automotive — 11 Ways To Know You May Need New Brakes",
        "https://www.aaa.com/autorepair/articles/11-ways-to-know-you-may-need-new-brakes",
    ),
    (
        "Vô lăng rung hoặc xe rung ở một khoảng tốc độ",
        "vô lăng rung, rung tay lái, xe rung tốc độ cao, rung khi chạy nhanh, bánh xe rung",
        "Hãy hỏi xe rung ở tốc độ nào, cảm nhận ở vô lăng hay ghế, có chỉ rung khi phanh hoặc tăng tốc không. "
        "Kỹ thuật viên cần kiểm tra tình trạng lốp, bánh xe, cân bằng bánh và các hệ thống liên quan "
        "theo thời điểm rung; không tự kết luận chỉ cần cân bằng lốp.",
        "Nếu rung mạnh đột ngột, lốp hư hại hoặc xe khó điều khiển, giảm tốc từ từ và dừng nơi an toàn để được kiểm tra.",
        "NHTSA — Tire Safety Ratings and Awareness (TireWise)",
        "https://www.nhtsa.gov/vehicle-safety/tires",
    ),
    (
        "Xe bị lệch lái hoặc kéo về một bên",
        "lệch lái, xe kéo về một bên, xe bị nhao lái, xe chạy không thẳng, vô lăng lệch",
        "Hãy hỏi xe kéo lệch khi chạy thẳng, khi phanh hay sau khi va ổ gà; kiểm tra áp suất và "
        "tình trạng lốp của hai bên. Kỹ thuật viên cần đánh giá lốp, góc đặt bánh, hệ thống lái "
        "và treo trên xe thật; không mặc định phải cân chỉnh bánh hoặc thay phụ tùng.",
        "Nếu khó giữ xe đi đúng hướng hoặc vô lăng mất kiểm soát, dừng nơi an toàn và gọi cứu hộ.",
        "Firestone Complete Auto Care — Six Common Suspension Problems",
        "https://www.firestonecompleteautocare.com/blog/maintenance/common-suspension-problems",
    ),
    (
        "Điều hòa xe không mát hoặc lúc lạnh lúc nóng",
        "điều hòa không lạnh, máy lạnh không mát, điều hòa lúc lạnh lúc nóng, gió điều hòa yếu",
        "Hãy hỏi gió thổi mạnh hay yếu, xe chỉ mất lạnh khi dừng hay cả khi chạy, và có mùi lạ không. "
        "Kỹ thuật viên có thể kiểm tra luồng gió, lọc gió cabin, rò rỉ môi chất lạnh, cụm máy nén "
        "và phần điện điều khiển tùy biểu hiện. Không tự kết luận thiếu gas hay tự đề nghị nạp gas khi chưa kiểm tra.",
        "Nếu điều hòa kèm mùi khét hoặc khói, dừng xe an toàn, tắt máy và liên hệ cứu hộ.",
        "Firestone Complete Auto Care — Car Air Conditioning Repair: Troubleshooting",
        "https://www.firestonecompleteautocare.com/blog/maintenance/car-air-conditioning-repair-troubleshooting",
    ),
    (
        "Xe khó nổ máy hoặc chỉ nghe tiếng tạch tạch",
        "khó nổ, khó đề, không nổ máy, đề không lên, tạch tạch khi đề, đề máy chậm",
        "Hãy hỏi khi đề máy có tiếng quay động cơ hay chỉ có tiếng tạch tạch, đèn bảng táp-lô "
        "có sáng không và xe dùng động cơ đốt trong, hybrid hay điện. Với xe xăng/dầu, "
        "ắc quy, mối nối điện và bộ đề là các hướng kiểm tra ban đầu; kỹ thuật viên cần đo kiểm "
        "thực tế, không khẳng định phải thay ắc quy. Xe hybrid/điện cần theo đúng quy trình an toàn của hãng.",
        "Nếu vừa ngập nước, có khói hoặc mùi khét, không thử đề lại; gọi cứu hộ.",
        "AAA Automotive — 14 Reasons Why Your Car Won't Start",
        "https://www.aaa.com/autorepair/articles/14-reasons-why-your-car-wont-start",
    ),
    (
        "Xe rung giật khi tăng tốc hoặc khi đứng yên",
        "xe rung giật, giật khi tăng ga, rung khi tăng tốc, máy rung khi đứng yên, máy chạy không đều",
        "Hãy hỏi hiện tượng xảy ra khi xe đứng yên hay tăng tốc, có đèn báo động cơ sáng hoặc "
        "nhấp nháy không. Có thể cần kiểm tra hệ thống truyền động, chân máy hoặc hoạt động "
        "động cơ tùy biểu hiện; không kết luận lỗi bugi, kim phun hay đề nghị thay phụ tùng khi chưa kiểm tra.",
        "Nếu xe rung mạnh, mất công suất hoặc đèn động cơ nhấp nháy, tấp vào nơi an toàn và gọi cứu hộ.",
        "Firestone Complete Auto Care — Why Is My Car Shaking?",
        "https://www.firestonecompleteautocare.com/blog/maintenance/why-is-my-car-shaking/",
    ),
    (
        "Đèn kiểm tra động cơ sáng hoặc nhấp nháy",
        "đèn check engine, đèn cá vàng, đèn động cơ sáng, đèn động cơ nhấp nháy, báo lỗi động cơ",
        "Hãy hỏi đèn sáng liên tục hay nhấp nháy, xe có rung, yếu máy hoặc mùi lạ không. "
        "Đèn báo có nhiều nguyên nhân; kỹ thuật viên cần đọc mã lỗi và kiểm tra xe để xác định "
        "nguyên nhân, không thay phụ tùng chỉ dựa vào đèn cảnh báo.",
        "Nếu đèn nhấp nháy, xe rung mạnh, yếu máy, có khói hoặc mùi lạ, dừng nơi an toàn và gọi cứu hộ.",
        "AAA Automotive — The Check Engine Light: Common Causes and How To Fix It",
        "https://www.aaa.com/autorepair/articles/buying-car/the-check-engine-light-common-causes-and-how-to-fix-it",
    ),
    (
        "Động cơ nóng bất thường hoặc kim nhiệt lên cao",
        "động cơ quá nhiệt, kim nhiệt tăng cao, xe nóng máy, nhiệt độ động cơ cao, nước làm mát sôi",
        "Hãy hỏi kim nhiệt/đèn cảnh báo có báo quá nhiệt không, có hơi nước hay rò rỉ chất lỏng không. "
        "Garage cần kiểm tra hệ thống làm mát, mức dung dịch và dấu hiệu rò rỉ sau khi xe đã nguội; "
        "không khẳng định hỏng két nước hay bơm nước khi chưa kiểm tra.",
        "Tấp vào nơi an toàn và tắt máy; không mở nắp két nước khi còn nóng, gọi cứu hộ kiểm tra trước khi chạy tiếp.",
        "AAA Automotive — Car Overheating: 8 Causes and Solutions",
        "https://www.aaa.com/autorepair/articles/car-overheating-8-causes-and-solutions",
    ),
]


def seed_reference_articles(db) -> int:
    """Chỉ bổ sung bài còn thiếu; không bao giờ tự xuất bản lại bài đã bị thu hồi."""
    author = db.execute("SELECT id FROM users WHERE email='admin@garage.vn'").fetchone()
    if not author:
        return 0
    inserted = 0
    levels = ("high", "high", "high", "high", "low", "medium", "medium", "high", "critical")
    with transaction(db):
        for (title, symptoms, content, safety, source_name, source_url), level in zip(ARTICLES, levels):
            if db.execute("SELECT 1 FROM technical_articles WHERE source_url=?", (source_url,)).fetchone():
                continue
            article_id = db.execute("""INSERT INTO technical_articles
                (title,symptoms,content,safety,source_name,source_url,status,created_by,safety_level)
                VALUES(?,?,?,?,?,?,'published',?,?)""",
                (title, symptoms, content, safety, source_name, source_url, author["id"], level)).lastrowid
            index_article_chunks(db, article_id, content)
            inserted += 1
    return inserted
