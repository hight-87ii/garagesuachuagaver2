"""Nguồn đã đọc trực tiếp cho 3/5 bài chờ xuất bản còn thiếu metadata.

Hai bài ID 28/29 đã có nguồn Bosch trong technical_source_reviews.py. Nguồn ở đây
được đối chiếu ngày 26/10/2026; giới hạn áp dụng được ghi rõ, không suy rộng thông
số hoặc quy trình của một hãng sang mọi xe.
"""

REVIEWS = {
    "Mã P0455 rò lớn hệ hơi nhiên liệu": {
        "source_name": "GM Service Bulletin 21-NA-124 — P0442/P0455",
        "source_url": "https://static.nhtsa.gov/odi/tsbs/2022/MC-10228888-0001.pdf",
        "document_version": "21-NA-124 v2, 12/2022; GM xăng 2000–2023",
        "sha256": "A35352FF48603068D9AACD46506D4F39CC979948AB877593560C32A81F96C1BF",
        "evidence": (
            "Trang 1–2 định nghĩa P0455 là EVAP large leak, yêu cầu dùng SI theo xe; "
            "kiểm tra đầu nối/ống, vent valve, purge valve, nắp bình và xác nhận bằng "
            "thử kín. Chỉ áp dụng Buick/Cadillac/Chevrolet/GMC động cơ xăng 2000–2023; "
            "bài vẫn yêu cầu đối chiếu VIN trước sửa."
        ),
    },
    "Lập báo giá sau khi chẩn đoán triệu chứng": {
        "source_name": "U.S. FTC Consumer Advice — Auto Repair Basics",
        "source_url": "https://consumer.ftc.gov/articles/0211-auto-repair-basics",
        "document_version": "Published 08/2012; truy cập 26/10/2026",
        "sha256": "",
        "evidence": (
            "Mục Repair Charges yêu cầu làm rõ phí chẩn đoán; báo giá viết phải nêu "
            "tình trạng cần sửa, phụ tùng và tiền công dự kiến, đồng thời liên hệ xin "
            "chấp thuận trước khi vượt giới hạn tiền/thời gian. Quy định địa phương có thể khác."
        ),
    },
    "An toàn khi xử lý xe điện và hybrid": {
        "source_name": "Lexus TSB L-SB-0091-13 — Hybrid Electrical Safety; OSHA 1910.333",
        "source_url": "https://static.nhtsa.gov/odi/tsbs/2013/MC-10132003-9999.pdf",
        "document_version": "L-SB-0091-13, 04/12/2013; CT 200h 2014",
        "sha256": "6985B8489DF059A9C99E1CE8251BC42A079FB3DB5DBB44352EA2DBF385066F55",
        "evidence": (
            "TSB trang 1,3–4: điện áp tới 650 V, chỉ người hoàn tất đào tạo, dùng găng "
            "cách điện/kính, không chạm dây cam/service plug, theo Repair Manual và cảnh "
            "báo riêng khi va chạm. OSHA 1910.333 yêu cầu khử điện, khóa/treo thẻ, xác "
            "minh hết điện và chỉ người đủ năng lực làm việc với phần mang điện. TSB áp "
            "dụng CT 200h 2014; mọi xe khác phải dùng quy trình OEM theo VIN."
        ),
        "secondary_url": "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.333",
    },
}
