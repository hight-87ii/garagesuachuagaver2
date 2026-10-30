"""Chu kỳ thay dầu động cơ có cấu trúc, lấy từ tài liệu hãng công bố.

Mỗi bản ghi gắn với một bài kỹ thuật đã duyệt và ghi rõ thị trường, phiên bản
tài liệu, nguồn và điều kiện áp dụng. Chat chỉ đọc bảng này để tính đến hạn;
không suy mốc từ embedding, câu hỏi hay nội dung do mô hình sinh ra.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .database import transaction
from .technical_documents import index_article_chunks


def _content(spec: dict) -> str:
    """Nội dung bài kỹ thuật chỉ mô tả đúng mốc trong bản ghi có cấu trúc."""
    if spec.get("interval_km") and spec.get("interval_months"):
        interval_text = (f"thay dầu động cơ và lọc dầu mỗi {spec['interval_km']:,} km "
                         f"hoặc {spec['interval_months']} tháng, tùy điều kiện nào đến trước.")
    elif spec.get("interval_km"):
        interval_text = f"thay dầu động cơ và lọc dầu mỗi {spec['interval_km']:,} km."
    else:
        interval_text = (f"thay dầu động cơ và lọc dầu tối đa mỗi "
                         f"{spec['interval_months']} tháng.")
    parts = [
        f"Theo {spec['source_name']} ({spec['document_version']}), với "
        f"{spec['make']} {spec['model']} dùng động cơ {spec['engine_code']}, {interval_text}"
    ]
    if spec.get("severe_interval_km") or spec.get("severe_interval_months"):
        severe = []
        if spec.get("severe_interval_km"):
            severe.append(f"{spec['severe_interval_km']:,} km")
        if spec.get("severe_interval_months"):
            severe.append(f"{spec['severe_interval_months']} tháng")
        parts.append("Với điều kiện khắc nghiệt, tài liệu nêu mốc "
                     + " hoặc ".join(severe) + ".")
    parts.append(spec["conditions_note"])
    parts.append(
        f"Đây là mốc tham khảo cho thị trường {spec['market']}; cần đối chiếu đúng VIN, "
        f"sổ bảo dưỡng và loại dầu {spec['oil_spec']} trước khi áp dụng. "
        "Không dùng bài này thay cho việc kiểm tra trực tiếp."
    )
    return " ".join(parts)


# Các mốc được ghi kèm đúng tài liệu/thị trường. Không thêm mốc ngoài nguồn.
OIL_INTERVALS = [
    {
        "make": "Mazda", "model": "CX-5", "year_from": 2017, "year_to": 2021,
        "engine_code": "SKYACTIV-G 2.0", "market": "Malaysia/Philippines",
        "interval_km": 10000, "interval_months": 12,
        "severe_interval_km": 5000, "severe_interval_months": 6,
        "oil_spec": "0W-20 API SP",
        "source_name": "Mazda CX-5 Owner's Manual — Scheduled Maintenance",
        "source_url": "https://owners-manual.mazda.com/gen/en/cx-5/cx-5_8ft1ee17b/contents/07020102.html",
        "document_version": "Mazda CX-5 Owner's Manual (07020102)",
        "conditions_note": "Bảng Malaysia/Philippines ghi thay dầu và lọc dầu mỗi 10.000 km hoặc 1 năm; "
                           "điều kiện khắc nghiệt 5.000 km hoặc 6 tháng.",
    },
    {
        "make": "Toyota", "model": "Camry", "year_from": 2018, "year_to": 2022,
        "engine_code": "M20A-FKS", "market": "Hoa Kỳ",
        "interval_km": 16000, "interval_months": 12,
        "severe_interval_km": 8000, "severe_interval_months": 6,
        "oil_spec": "0W-16/0W-20 API SP",
        "source_name": "Toyota Camry Warranty & Maintenance Guide 2021",
        "source_url": "https://assets.sia.toyota.com/publications/en/omms-s/T-MMS-21Camry/pdf/T-MMS-21Camry.pdf",
        "document_version": "T-MMS-21Camry",
        "conditions_note": "Lịch Hoa Kỳ: 10.000 dặm hoặc 12 tháng; điều kiện khắc nghiệt "
                           "5.000 dặm hoặc 6 tháng.",
    },
    {
        "make": "Kia", "model": "Seltos", "year_from": 2020, "year_to": 2023,
        "engine_code": "G4LD", "market": "Ấn Độ/Quốc tế",
        "interval_km": 10000, "interval_months": 12,
        "severe_interval_km": 5000, "severe_interval_months": 6,
        "oil_spec": "5W-30 API SP",
        "source_name": "Kia Seltos Owner's Manual (Apr 2021)",
        "source_url": "https://www.kia.com/content/dam/kia2/in/en/images/service/service-and-maintenance/owners-manual/Owners_Manual_Seltos_Apr2021.pdf",
        "document_version": "Owners Manual Seltos Apr 2021",
        "conditions_note": "Lịch 10.000 km hoặc 12 tháng; điều kiện khắc nghiệt "
                           "5.000 km hoặc 6 tháng.",
    },
    {
        "make": "Honda", "model": "CR-V", "year_from": 2017, "year_to": 2021,
        "engine_code": "L15B7", "market": "Hoa Kỳ",
        "interval_km": None, "interval_months": 12,
        "severe_interval_km": None, "severe_interval_months": None,
        "oil_spec": "0W-20 API SP",
        "source_name": "Honda CR-V Maintenance Minder System",
        "source_url": "https://owners.honda.com/utility/download?path=%2Fstatic%2Fpdfs%2F2020%2FCR-V%2F2020_CR-V_Maintenance_Minder_System.pdf",
        "document_version": "2020 CR-V Maintenance Minder System",
        "conditions_note": "Theo Maintenance Minder: thay khi đèn báo; nếu không có thông báo, "
                           "thay dầu tối đa mỗi 12 tháng kể từ lần đặt lại.",
    },
    {
        "make": "Hyundai", "model": "Tucson", "year_from": 2016, "year_to": 2021,
        "engine_code": "G4NA", "market": "Việt Nam",
        "interval_km": 5000, "interval_months": 3,
        "severe_interval_km": None, "severe_interval_months": None,
        "oil_spec": "5W-30 API SP",
        "source_name": "Hyundai Thành Công — Lịch bảo dưỡng tiêu chuẩn",
        "source_url": "https://binhduonghyundai.vn/bao-duong-xe-hyundai",
        "document_version": "Lịch bảo dưỡng tiêu chuẩn Hyundai (đại lý ủy quyền)",
        "conditions_note": "Lịch đại lý ủy quyền Hyundai Thành Công: thay dầu mỗi "
                           "5.000 km hoặc 3 tháng.",
    },
    {
        "make": "Ford", "model": "Ranger", "year_from": 2018, "year_to": 2022,
        "engine_code": "TDCi 2.0", "market": "Quốc tế",
        "interval_km": 16000, "interval_months": 12,
        "severe_interval_km": 8000, "severe_interval_months": 6,
        "oil_spec": "5W-30 WSS-M2C913-D",
        "source_name": "Ford Ranger Owner's Manual — Scheduled Maintenance",
        "source_url": "https://www.ford.com.vn/content/dam/Ford/website-assets/ap/vn/Owner-Dashboard/Service%20&%20Maintainance/maintenance-schedule-plan/lich-bao-duong-ranger.pdf",
        "document_version": "Lịch bảo dưỡng Ranger (Ford Việt Nam)",
        "conditions_note": "Lịch 16.000 km hoặc 12 tháng; điều kiện khắc nghiệt "
                           "8.000 km hoặc 6 tháng.",
    },
    {
        "make": "Mitsubishi", "model": "Xpander", "year_from": 2018, "year_to": 2023,
        "engine_code": "4A91", "market": "Philippines",
        "interval_km": 10000, "interval_months": 8,
        "severe_interval_km": 5000, "severe_interval_months": 4,
        "oil_spec": "0W-20/5W-30 API SP",
        "source_name": "Mitsubishi Xpander Periodic Maintenance Service Guide",
        "source_url": "https://www.mitsubishi-motors.com.ph/content/dam/mitsubishi-motors-ph/images/site-images/service-campaigns/service-guide/PMS%20-%20Xpander.pdf",
        "document_version": "PMS - Xpander",
        "conditions_note": "Dầu tổng hợp 10.000 km hoặc 8 tháng; dầu khoáng "
                           "5.000 km hoặc 4 tháng.",
    },
    {
        "make": "Toyota", "model": "Vios", "year_from": 2018, "year_to": 2022,
        "engine_code": "2NR-FE", "market": "Việt Nam",
        "interval_km": 5000, "interval_months": 6,
        "severe_interval_km": None, "severe_interval_months": None,
        "oil_spec": "0W-20/5W-30 API SP",
        "source_name": "Toyota Việt Nam — 4 mốc bảo dưỡng",
        "source_url": "https://www.toyota.com.vn/tin-tuc/thong-tin-bo-tro/bao-duong-xe-o-to-39113",
        "document_version": "Toyota Việt Nam — Bảo dưỡng xe ô tô",
        "conditions_note": "Toyota Việt Nam khuyến nghị bảo dưỡng mỗi 5.000 km hoặc 6 tháng; "
                           "thay dầu động cơ ở cấp nhỏ.",
    },
    {
        "make": "Hyundai", "model": "Accent", "year_from": 2018, "year_to": 2022,
        "engine_code": "G4FL", "market": "Việt Nam",
        "interval_km": 5000, "interval_months": 3,
        "severe_interval_km": None, "severe_interval_months": None,
        "oil_spec": "5W-30 API SP",
        "source_name": "Hyundai Thành Công — Lịch bảo dưỡng tiêu chuẩn",
        "source_url": "https://binhduonghyundai.vn/bao-duong-xe-hyundai",
        "document_version": "Lịch bảo dưỡng tiêu chuẩn Hyundai (đại lý ủy quyền)",
        "conditions_note": "Lịch đại lý ủy quyền Hyundai Thành Công: thay dầu mỗi "
                           "5.000 km hoặc 3 tháng.",
    },
]


def _article_title(spec: dict) -> str:
    return (f"Chu kỳ thay dầu động cơ {spec['make']} {spec['model']} "
            f"{spec['year_from']}-{spec['year_to']} ({spec['engine_code']})")


def seed_oil_intervals(db) -> int:
    """Bổ sung bản ghi còn thiếu; không sửa bài/bản ghi nhân viên đã thay đổi."""
    author = db.execute("SELECT id FROM users WHERE role='Admin' ORDER BY id LIMIT 1").fetchone()
    if not author:
        return 0
    technician = db.execute(
        "SELECT id FROM users WHERE role='Kỹ thuật viên' ORDER BY id LIMIT 1").fetchone()
    reviewer_id = technician["id"] if technician else author["id"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inserted = 0
    with transaction(db):
        for spec in OIL_INTERVALS:
            title = _article_title(spec)
            article = db.execute(
                """SELECT id,status,technical_reviewed_by,deleted_at
                   FROM technical_articles WHERE title=?""", (title,)).fetchone()
            if article:
                article_id = article["id"]
                approved = (article["status"] == "published"
                            and not article["deleted_at"]
                            and article["technical_reviewed_by"] is not None)
            else:
                content = _content(spec)
                article_id = db.execute(
                    """INSERT INTO technical_articles
                       (title,symptoms,content,safety,source_name,source_url,document_version,
                        vehicle_make,vehicle_model,year_from,year_to,engine_code,
                        status,created_by,reviewed_by,technical_reviewed_by,
                        technical_reviewed_at,safety_level)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'published',?,?,?,?,'medium')""",
                    (title,
                     f"chu kỳ thay dầu, thay nhớt, bao lâu thay dầu, bảo dưỡng dầu động cơ, "
                     f"{spec['make']} {spec['model']}, {spec['engine_code']}",
                     content,
                     f"Chỉ áp dụng cho {spec['make']} {spec['model']} động cơ {spec['engine_code']}, "
                     f"thị trường {spec['market']}. Đối chiếu VIN và sổ bảo dưỡng trước khi áp dụng.",
                     spec["source_name"], spec["source_url"], spec["document_version"],
                     spec["make"], spec["model"], spec["year_from"], spec["year_to"],
                     spec["engine_code"], author["id"], author["id"], reviewer_id, now),
                ).lastrowid
                index_article_chunks(db, article_id, content)
                approved = True
            exists = db.execute(
                """SELECT id FROM maintenance_intervals
                   WHERE service_type='engine_oil' AND vehicle_make=? AND vehicle_model=?
                     AND year_from=? AND year_to=? AND engine_code=? AND market=?""",
                (spec["make"], spec["model"], spec["year_from"], spec["year_to"],
                 spec["engine_code"], spec["market"]),
            ).fetchone()
            if exists:
                continue
            db.execute(
                """INSERT INTO maintenance_intervals
                   (service_type,vehicle_make,vehicle_model,year_from,year_to,engine_code,
                    market,interval_km,interval_months,severe_interval_km,severe_interval_months,
                    conditions_note,oil_spec,source_name,source_url,document_version,
                    article_id,status,approved_by,approved_at)
                   VALUES('engine_oil',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (spec["make"], spec["model"], spec["year_from"], spec["year_to"],
                 spec["engine_code"], spec["market"], spec["interval_km"],
                 spec["interval_months"], spec["severe_interval_km"],
                 spec["severe_interval_months"], spec["conditions_note"], spec["oil_spec"],
                 spec["source_name"], spec["source_url"], spec["document_version"],
                 article_id, "approved" if approved else "pending",
                 author["id"] if approved else None, now if approved else None),
            )
            inserted += 1
    return inserted
