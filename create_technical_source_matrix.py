"""Tạo CSV ứng viên 97 bài từ bản thảo + database; chỉ đọc DB, không xác minh/duyệt.

    python -X utf8 create_technical_source_matrix.py

MAPPING là vị trí trong ASE Automobile Study Guide ©2026 (số trang in trên PDF).
Nội dung ASE là danh mục kỹ năng thi; cột phạm vi là chủ đề có liên quan, KHÔNG
phải bằng chứng xác nhận mọi nguyên nhân, cảnh báo hay quy trình trong bài.
"""

import csv
import hashlib
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from backend.database import connect
from backend.technical_expansion_data import GROUPS, articles
from backend.technical_source_reviews import REVIEWS
from backend.pending_publish_source_reviews import REVIEWS as PUBLISHED_REVIEWS

OUTPUT = Path(__file__).with_name("TECHNICAL_SOURCE_MATRIX_97.csv")
ASE = "https://www.ase.com/wp-content/uploads/ASE_Automobile_Study_Guide.pdf"
ASE_NAME = "ASE — Automobile Study Guide ©2026"
ASE_SHA256 = "3A5A4F364498D681BBF320ED9227DEA5C3BB05AE1F3EAB3FBA6DB4F624F34B25"

# ID dự kiến khi nhập vào database gốc; tiêu đề được so lại với database trước khi ghi.
# ID | trang in trên PDF | mục thực sự liên quan (KHÔNG đại diện chứng minh toàn bài).
MAPPING = """
10|7|A1.D.6-8: thử kín và kiểm tra rò hệ làm mát
11|7|A1.D.12: quạt làm mát và mạch điện liên quan
12|7|A1.D.12: thử quạt và mạch điện liên quan
13|44-45|A8.A/B/C: chẩn đoán rung không tải, khí nạp, đánh lửa, nhiên liệu
14|44-45|A8.A/C: kiểm tra vấn đề vận hành, nhiên liệu và khí nạp
15|44,48|A8.A.5: màu khí xả; câu hỏi mẫu về khói xanh
16|44|A8.A.5/14: màu khí xả, nước làm mát và thử áp
17|45|A8.C.3: kiểm tra bình nhiên liệu, ống và đầu nối
18|5,44|A1.A/A8.A.4: xác định tiếng và rung động cơ
19|7,46|A1.D.1-2/A8.D.1: áp suất, rò và thông hơi dầu
20|7|A1.D.2: thử rò dầu động cơ
21|45|A8.B/C.1: khó nổ nóng, đánh lửa và cấp nhiên liệu
22|44-45|A8.A/C.1: xác minh tắt máy và tốc độ không tải
23|7|A1.D.1: thử áp suất hệ bôi trơn
24|7,40|A1.D.9/A7.A.25: thermostat và nhiệt độ động cơ
25|27-28|A5.A: hành trình bàn đạp, rò và xả khí hệ thủy lực
26|27-28|A5.A.20-24: trợ lực phanh và hành trình bàn đạp
27|29|A5.D.3-7: đèn ABS, đọc lỗi và cảm biến
30|28|A5.A.25-29: phanh đỗ điện tử và thao tác theo hãng
31|28|A5.A.25-27: cáp, điều chỉnh và thử phanh đỗ
32|27|A5.A.4-14: rò và công tắc/đèn cảnh báo phanh
33|28-29|A5.A.15/C.1-7: phanh kéo/bó và kẹp phanh
35|29|A5.C.2/5-6: tiếng phanh, chốt và phần cứng giữ má
36|23,29|A4.D.2-3/A5.D.2: tình trạng lốp và hiện tượng khóa bánh
37|21|A4.A.4-11: lực lái và hệ trợ lực
38|21|A4.A.7-11: nguồn tiếng hệ trợ lực và dây đai
39|21-23|A4.A.5-6/C: kẹt cơ cấu lái và góc đặt bánh
40|22|A4.B.1/12: chất lượng êm dịu và giảm chấn
41|21-22|A4.A/B: tiếng cơ cấu lái và gối đỡ treo
42|22|A4.B.1/16: chiều cao thân xe và lò xo/treo
43|21-22|A4.A/B: tiếng cơ cấu lái, rotuyn và liên kết treo
44|22|A4.B: tiếng treo và kiểm tra cao su/giảm chấn
45|21-22|A4.A.5-6/25: độ rơ cơ cấu lái và thanh kéo
46|22|A4.B.1/9/12: lắp giảm chấn, gối đỡ và chất lượng chạy
47|21-22|A4.A.4/20: trợ lực điện, mô-tơ, cảm biến và dây
48|22-23|A4.B/C/D: treo, góc đặt và lốp sau va đập
49|33-34|A6.A.9/B: dòng tiêu thụ khi tắt máy và thử ắc quy
50|34|A6.C: đo đầu ra và mạch sạc
51|34|A6.D.1-3: mạch đèn ngoài và giắc
52|35|A6.E.4: phụ kiện tiện nghi/kính điện và mạch
53|35|A6.E.4: gạt mưa và phụ kiện điện thân xe
54|35|A6.E.9-10: chẩn đoán hệ thống an toàn/SRS
55|35,38|A6.E.4: mạch còi; câu hỏi mẫu về rơ-le còi
56|35|A6.E.7-8: khóa cửa, chìa không dây và mạch
57|34-35|A6.E.2/9: hỗ trợ đỗ xe, cảm biến và mạch
58|34-35|A6.E.2/9: camera, hỗ trợ đỗ và mạch điện
59|23|A4.D.10: chẩn đoán TPMS trực tiếp/gián tiếp
60|33-34|A6.A/B: điều kiện điện áp và tình trạng ắc quy
61|34-35|A6.E.1-2: màn hình/giải trí và đường tín hiệu
62|34|A6.D.4-5: mạch xi nhan và đèn cảnh báo
63|33|A6.A.8/10-11: chập điện và kiểm tra cầu chì theo sơ đồ
64|10-11|A2.A.9/23: chất lượng chuyển số cơ/điện tử
65|10-11|A2.A.4/8/11: mức dầu, trễ vào số và áp suất
66|16-17|A3.A/B: côn, khó vào số và đồng tốc
67|16|A3.A.1/5: hiện tượng trượt côn và lá côn
68|16|A3.A.1/4: tiếng côn và bi tê
69|18|A3.E.1/9: tiếng và rung vi sai/cầu xe
70|17|A3.D.1-2: tiếng khớp đồng tốc, chụp bụi
71|11,17|A2.B.3/A3.D: phớt trục và khớp dẫn động
72|10-11|A2.A.9/B.11: rung khi vào số và chân máy
73|10-11,14|A2.A/B: dầu, làm mát hộp số và câu hỏi mẫu quá nhiệt
74|41|A7.C.1-2: quạt gió và bộ điều tốc/điện trở
75|39-41|A7.A.10/B.14-16: lọc cabin, dàn lạnh và thoát nước
76|40|A7.B.16: vỏ dàn lạnh và ống thoát nước
77|40-41|A7.B.9/C.6: lưu lượng dàn nóng và quạt làm mát
78|35|A6.E.5-6: sấy kính và mạch điều khiển
79|35|A6.E.4: mô-tơ ghế và phụ kiện tiện nghi
81|40-41|A7.A.21/C: chẩn đoán mờ kính và phân phối gió
82|7|A1.D.5: dầu máy theo loại/độ nhớt/chất lượng của hãng
83|45|A8.C.9: kiểm tra hệ lọc khí nạp
84|39|A7.A.10: kiểm tra/thay lọc gió cabin
85|28|A5.A.16-18: dầu phanh đúng loại và xả khí
86|7,40|A1.D.11/A7.A.26: nước làm mát đúng loại và xả khí
87|7|A1.D.13: dây đai, puly, tăng đai
88|45|A8.B: kiểm tra hệ đánh lửa (không đưa chu kỳ bugi)
89|23|A4.D.5: đảo lốp và siết theo khuyến nghị hãng
90|33-34|A6.B/C: thử ắc quy và hệ sạc
91|10-11|A2.A.1/4/B.12: xác định loại hộp số và dầu phù hợp
92|34|A6.D: kiểm tra đèn chiếu sáng, xi nhan và mạch
94|23|A4.C/D.1: góc đặt và kiểu mòn gai lốp
95|23|A4.D.1-3: mòn gai và áp suất lốp
96|23|A4.D.2: kiểm tra tình trạng lốp và thành lốp
97|23|A4.D.4/6: rung và độ đảo mâm/bánh
98|23|A4.D.2-3: tình trạng lốp và kiểm tra áp suất
99|23|A4.D.1/4: mòn gai dạng bất thường và tiếng lốp
100|44-46|A8.A/B/C: bỏ máy, dữ liệu máy quét và nguyên nhân nhóm
101|45|A8.C.1-2/11: nhiên liệu/khí nạp và fuel trim
102|45-46|A8.C.12-13/D.3: xả, cảm biến O2 và xúc tác
103|7,44|A1.D.9/A8.A.14: thermostat và nhiệt độ động cơ
104|45-46|A8.C.3/D.4: nắp bình và kiểm tra hệ EVAP
105|5,27|A1.A/A5.A: xác minh triệu chứng và ưu tiên hệ phanh
106|5,23,29|A1.A/A4.D/A5.C: xác minh chạy thử, bánh/lốp, phanh
"""

# Liên kết thứ hai chỉ hỗ trợ chủ đề rộng; trạng thái đọc được gắn rõ, KHÔNG
# chuyển thành nguồn đã xác minh cho bài. Một dòng duy nhất cho mỗi bài.
SECONDARY = {
    10: ("Car Care Council — Vehicle Systems Overview", "https://www.carcare.org/vehicle-systems-overview", "Đã đọc trang tổng quan; chỉ đề cập kiểm tra mức nước và lịch hãng"),
    49: ("Bosch Car Service — Vehicle maintenance", "https://ap.boschcarservice.com/in/en/car-services/car-inspection-and-checks/car-periodic-maintenance", "Đã đọc trang dịch vụ chung; không có ngưỡng dòng rò"),
    82: ("Bosch Car Service — Vehicle maintenance", "https://ap.boschcarservice.com/in/en/car-services/car-inspection-and-checks/car-periodic-maintenance", "Đã đọc trang bảo dưỡng; không có cấp dầu cụ thể theo VIN"),
    85: ("Bosch Car Service — Brake Repair & Maintenance", "https://ap.boschcarservice.com/in/en/car-services/car-brake-service/brake-repair-and-maintenance", "Đã đọc trang phanh tổng quát; không cung cấp chu kỳ dầu cho mọi xe"),
    86: ("Car Care Council — Vehicle Systems Overview", "https://www.carcare.org/vehicle-systems-overview", "Đã đọc; nhắc đối chiếu sổ tay xe về nước làm mát"),
    89: ("Car Care Council — Vehicle Systems Overview", "https://www.carcare.org/vehicle-systems-overview", "Đã đọc trang tổng quan; không cho sơ đồ đảo lốp từng xe"),
    90: ("Bosch Car Service — Vehicle maintenance", "https://ap.boschcarservice.com/in/en/car-services/car-inspection-and-checks/car-periodic-maintenance", "Đã đọc; chỉ là danh mục kiểm tra ắc quy"),
    94: ("Bridgestone — Tire Tread Wear & Causes", "https://www.bridgestonetire.com/learn/maintenance/tire-tread-wear-causes", "Chỉ trích tìm kiếm; trang toàn văn bị chặn 403"),
    95: ("NHTSA — TireWise", "https://www.nhtsa.gov/vehicle-safety/tires", "Chỉ trích tìm kiếm; trang toàn văn bị chặn 403"),
    96: ("Bridgestone — Tire Maintenance and Safety Manual", "https://www.bridgestonetire.com/content/dam/consumer/bst/na/warranties/bridgestone_firestone_canada_maint_safety_manual_05-12-17_v2.pdf", "Chỉ trích tìm kiếm; PDF nguồn bị chặn 403; không khẳng định phiên bản"),
    99: ("Bridgestone — Tire Cupping: What It Means, Causes, and What to Do", "https://www.bridgestonetire.com/learn/maintenance/tire-cupping", "Chỉ trích tìm kiếm; trang toàn văn bị chặn 403"),
}

# ASE không nói riêng mã P0xxx, điều kiện đặt mã, VIN, số đo, quyền thao tác cao áp.
SPECIAL_GAPS = {
    54: "Cần tài liệu OEM SRS theo VIN và người có chứng chỉ; ASE không hướng dẫn cô lập/kích nổ cho từng xe.",
    59: "Cần tài liệu TPMS theo VIN để phân biệt cảm biến/hiệu chuẩn.",
    60: "Cần điều kiện cho phép start-stop và mã lỗi theo xe; ASE chỉ nêu chẩn đoán điện 12 V.",
    82: "Phải tra cấp SAE/tiêu chuẩn dầu, dung tích và chu kỳ từ sổ tay theo VIN.",
    85: "Chu kỳ thay và loại dầu phanh phải tra từ sổ tay theo VIN.",
    86: "Loại nước làm mát, tỷ lệ pha và chu kỳ phải tra theo xe.",
    88: "Chu kỳ, mã bugi và mô-men lắp phải tra theo VIN; phần ASE chỉ nói đánh lửa.",
    89: "Sơ đồ đảo lốp cần loại dẫn động, kích thước và lốp một chiều theo xe.",
    91: "Loại dầu, nhiệt độ đo mức và chu kỳ hộp số phải tra theo VIN.",
    96: "ASE chỉ nêu kiểm tra tình trạng lốp; chưa đủ chứng minh phương án thay/vá thành lốp.",
    100: "ASE không nêu P0300 hay freeze-frame riêng cho từng xe; cần định nghĩa/tiêu chí đặt mã của OEM.",
    101: "ASE không nêu P0171 hay ngưỡng fuel trim; cần định nghĩa và đo theo OEM.",
    102: "ASE không nêu P0420 hay ngưỡng giám sát xúc tác; cần định nghĩa và đo theo OEM.",
    103: "ASE không nêu P0128 hay nhiệt độ ngưỡng; cần định nghĩa/điều kiện đặt mã OEM.",
    104: "ASE không nêu P0455 hay ngưỡng rò; cần định nghĩa và thủ tục thử EVAP theo OEM.",
    105: "Danh mục ASE không quy định phân loại đèn đỏ hay quy trình tiếp nhận của garage; cần nguồn an toàn độc lập.",
    106: "ASE liệt kê chạy thử từng hệ, chưa xác nhận checklist an toàn trước lái thử của garage.",
}

# Các bài này không có đoạn ASE đủ sát để gán cho nội dung chính.
NO_FIT = {
    80: "ASE A6 đề cập khóa/mạch cửa, không chứng minh chỉnh bản lề hoặc độ ngậm chốt cửa; cần tài liệu thân vỏ theo VIN.",
    93: "ASE không xác nhận quy trình lưu hồ sơ/vật tư và lời khuyên bán hàng; cần chính sách garage và sổ bảo dưỡng hãng.",
    107: "ASE không quy định báo giá, quyền đồng ý sửa chữa; cần quy trình garage và quy định bảo vệ người tiêu dùng.",
    108: "ASE A7.19 chỉ nhắc thiết bị cho điều hòa hybrid/EV; KHÔNG đủ cho cô lập cao áp. Cần quy trình OEM theo VIN, chứng chỉ và bảo hộ.",
    109: "ASE không chứng minh nội dung bàn giao và cam kết sửa chữa; cần quy trình garage và phiếu công việc thực tế.",
}


def create(output: Path = OUTPUT) -> list[dict]:
    entries = {}
    for line in MAPPING.strip().splitlines():
        id_text, pages, scope = line.split("|", 2)
        article_id = int(id_text)
        if article_id in entries:
            raise ValueError(f"ID trùng: {article_id}")
        entries[article_id] = (pages, scope)

    drafts = [(group, item.title) for group, item in articles() if item.title not in REVIEWS]
    assert len(drafts) == 97
    with connect() as db:
        rows = {row["title"]: dict(row) for row in db.execute(
            "SELECT id,title,status,source_name,source_url,document_version,technical_reviewed_by,reviewed_by "
            "FROM technical_articles WHERE deleted_at IS NULL")}
    result = []
    for group, title in drafts:
        if title not in rows:
            raise ValueError(f"Bài không có trong database: {title}")
        db_row = rows[title]
        article_id = db_row["id"]
        reviewed = PUBLISHED_REVIEWS.get(title)
        demo = (db_row["source_name"] == "Nội dung demo do AI tổng hợp" and
                db_row["document_version"] == "Demo, chưa xác minh")
        if reviewed:
            if (db_row["status"] != "published" or db_row["source_url"] != reviewed["source_url"] or
                    not db_row["technical_reviewed_by"] or not db_row["reviewed_by"]):
                raise ValueError(f"Bài đã xuất bản không khớp dấu vết nguồn: {article_id}: {title}")
            source, url = reviewed["source_name"], reviewed["source_url"]
            pages, scope = "", "Xem evidence trong backend/pending_publish_source_reviews.py"
            sha = reviewed.get("sha256", "")
            gap = reviewed["evidence"]
            level = "đã đối chiếu nguồn; đã duyệt chuyên môn và xuất bản"
        elif demo:
            if (db_row["status"] != "published" or db_row["source_url"] or
                    not db_row["technical_reviewed_by"] or not db_row["reviewed_by"]):
                raise ValueError(f"Bài demo xuất bản không khớp workflow: {article_id}: {title}")
            if article_id in NO_FIT:
                pages = scope = source = url = sha = ""
                gap = NO_FIT[article_id]
            else:
                pages, scope = entries[article_id]
                source, url, sha = ASE_NAME, ASE, ASE_SHA256
                gap = SPECIAL_GAPS.get(article_id,
                    "ASE chỉ là tài liệu nền; bài đang xuất bản dưới nhãn demo AI và chưa được xác minh kỹ thuật thực tế.")
            level = "nguồn ứng viên; bài đã xuất bản dưới nhãn demo AI chưa xác minh"
        elif db_row["status"] != "draft" or db_row["source_url"] or db_row["technical_reviewed_by"] or db_row["reviewed_by"]:
            raise ValueError(f"Bài đã đổi nguồn/trạng thái, cần đối chiếu lại: {article_id}: {title}")
        elif article_id in NO_FIT:
            pages = scope = source = url = sha = ""
            gap = NO_FIT[article_id]
            level = "chưa có nguồn phù hợp"
        else:
            pages, scope = entries[article_id]
            source, url, sha = ASE_NAME, ASE, ASE_SHA256
            gap = SPECIAL_GAPS.get(article_id,
                "ASE chỉ liệt kê năng lực/đầu mục kiểm tra; chưa đối chiếu từng nguyên nhân, cảnh báo, thao tác hoặc thông số theo VIN.")
            level = "đã đọc tài liệu nền; chưa đối chiếu từng nhận định"
        extra = SECONDARY.get(article_id, ("", "", ""))
        if reviewed and reviewed.get("secondary_url"):
            extra = ("OSHA 1910.333 — Selection and use of work practices",
                     reviewed["secondary_url"], "Đã đọc trực tiếp; yêu cầu khử điện, LOTO và người đủ năng lực")
        result.append({
            "article_id": article_id, "nhom": group, "tieu_de": title,
            "nguon_ung_vien": source, "url": url, "muc_trang_lien_quan": f"trang PDF {pages}; {scope}" if pages else "",
            "sha256_pdf_da_doc": sha, "nguon_bo_sung": extra[0], "url_bo_sung": extra[1],
            "cach_tiep_can_nguon_bo_sung": extra[2], "muc_do_doi_chieu": level,
            "gioi_han_va_viec_can_lam": gap,
            "trang_thai_database": ("published — đã duyệt nguồn/chuyên môn" if reviewed else
                                     "published — DEMO AI chưa xác minh" if demo else
                                     "draft — chưa xác minh nguồn"),
        })

    assert len(result) == 97 and len({row["article_id"] for row in result}) == 97
    assert set(entries) | set(NO_FIT) == {row["article_id"] for row in result}
    assert not set(entries) & set(NO_FIT)
    assert Counter(row["nhom"] for row in result) == {
        group: count - sum(item.title in REVIEWS for g, item in articles() if g == group)
        for group, count in GROUPS}
    for row in result:
        for field in ("url", "url_bo_sung"):
            if row[field] and urlparse(row[field]).scheme != "https":
                raise ValueError(f"URL không hợp lệ: {row[field]}")
    pdf = Path.home() / "AppData/Local/Temp/opencode/ASE_Automobile_Study_Guide.pdf"
    if pdf.is_file() and hashlib.sha256(pdf.read_bytes()).hexdigest().upper() != ASE_SHA256:
        raise ValueError("Bản PDF ASE đã đọc không còn khớp SHA-256")
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=result[0].keys())
        writer.writeheader()
        writer.writerows(result)
    return result


if __name__ == "__main__":
    rows = create()
    print(f"{OUTPUT}: {len(rows)} bài; {sum(bool(row['url']) for row in rows)} có URL nguồn chính; "
          f"{sum(bool(row['url_bo_sung']) for row in rows)} có liên kết thứ hai; "
          f"0 bài mới xác minh/duyệt/xuất bản")
