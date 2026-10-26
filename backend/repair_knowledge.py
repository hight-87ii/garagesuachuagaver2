"""Ca sửa chữa: chụp nháp từ phiếu hoàn thành, chỉ ca đã duyệt mới tra cứu công khai."""

import re
import sqlite3

from .technical_knowledge import _fold, _applies, STOPWORDS
from .vector_search import search_vectors


def capture_completed_case(db: sqlite3.Connection, order_id: int) -> int | None:
    """Chỉ INSERT một lần; không ghi đè hiệu đính của kỹ thuật viên nếu gọi lại."""
    order = db.execute("""SELECT r.*,v.make,v.model,v.year,v.engine_code
        FROM repair_orders r LEFT JOIN vehicles v ON v.id=r.vehicle_id WHERE r.id=?""", (order_id,)).fetchone()
    if not order or order["status_code"] not in ("COMPLETED", "DELIVERED") or not order["vehicle_id"]:
        return None
    tasks = [row["name"] for row in db.execute(
        "SELECT name FROM repair_order_items WHERE repair_order_id=? ORDER BY id", (order_id,))]
    tasks += [row["name"] for row in db.execute(
        "SELECT name FROM repair_order_parts WHERE repair_order_id=? ORDER BY id", (order_id,))]
    cursor = db.execute("""INSERT OR IGNORE INTO repair_knowledge_cases(
        repair_order_id,vehicle_id,vehicle_make,vehicle_model,vehicle_year,engine_code,
        customer_symptoms,inspection_findings,work_done)
        VALUES(?,?,?,?,?,?,?,?,?)""", (order_id, order["vehicle_id"], order["make"] or "",
        order["model"] or "", order["year"], order["engine_code"] or "",
        (order["customer_request"] or order["initial_condition"] or "")[:2000],
        (order["inspection_notes"] or "")[:2000], "; ".join(dict.fromkeys(tasks))[:4000]))
    row = db.execute("SELECT id FROM repair_knowledge_cases WHERE repair_order_id=?", (order_id,)).fetchone()
    return row["id"] if row else cursor.lastrowid


def contains_private_identifier(text: str) -> bool:
    """Lọc tín hiệu PII rõ ràng; quản lý vẫn cần đọc và ẩn danh trước khi xuất bản."""
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
        return True
    if re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", text.upper()):
        return True
    if re.search(r"\b(?:\+84|0)(?:[ .-]*\d){9,10}\b", text):
        return True
    if re.search(r"\b\d{2}[A-Z]{1,2}[- ]?\d{3}[.-]?\d{2}\b", text.upper()):
        return True
    return False


def search_repair_cases(db: sqlite3.Connection, question: str,
                        vehicle: dict | None, limit: int = 2) -> list[dict]:
    """Không chọn đúng hồ sơ xe thì không đưa ca của xe khác vào prompt."""
    if not vehicle or not vehicle.get("make") or not vehicle.get("model"):
        return []
    tokens = list(dict.fromkeys(word for word in re.findall(r"[a-z0-9]+", _fold(question))
                                if len(word) > 1 and word not in STOPWORDS))[:8]
    original = re.findall(r"[^\W_]+", question.casefold(), flags=re.UNICODE)
    terms = list(dict.fromkeys([*tokens, *(word for word in original if _fold(word) in tokens)]))
    match = " OR ".join('"' + word.replace('"', '') + '"' for word in terms)
    rows = db.execute("""SELECT c.* FROM repair_case_fts f
        JOIN repair_knowledge_cases c ON c.id=f.rowid
        WHERE repair_case_fts MATCH ? AND c.status='published'
        ORDER BY bm25(repair_case_fts, 8.0, 1.0, 1.0, 1.0, 1.0) LIMIT 50""", (match,)).fetchall() if tokens else []
    lexical_rank = {row["id"]: rank for rank, row in enumerate(rows)}
    semantic_rank = {case_id: rank for rank, (case_id, _score) in enumerate(
        search_vectors(db, question, "repair_case"))}
    seen = set(lexical_rank)
    for case_id in semantic_rank:
        if case_id not in seen:
            row = db.execute("SELECT * FROM repair_knowledge_cases WHERE id=? AND status='published'",
                             (case_id,)).fetchone()
            if row:
                rows.append(row)
    results = []
    for row in rows:
        case = dict(row)
        rule = {"vehicle_make": case["vehicle_make"], "vehicle_model": case["vehicle_model"],
                "year_from": case["vehicle_year"], "year_to": case["vehicle_year"],
                "engine_code": case["engine_code"]}
        if not _applies(rule, vehicle) or (case["id"] not in semantic_rank and not any(
                token in _fold(case["customer_symptoms"]).split() for token in tokens)):
            continue
        # Ca chỉ là kinh nghiệm đối chiếu, không thay cho chẩn đoán xe đang hỏi.
        results.append({"id": case["id"], "source_type": "repair_case",
            "title": f"Ca sửa chữa tham khảo {case['vehicle_make']} {case['vehicle_model']}",
            "symptoms": case["customer_symptoms"], "content": (
                f"Một ca trước ghi khách báo: {case['customer_symptoms']}. Kỹ thuật viên kiểm tra: "
                f"{case['inspection_findings']}. Nguyên nhân đã xác nhận cho ca đó: {case['confirmed_cause']}. "
                f"Hạng mục thực hiện: {case['work_done']}. Kết quả sau sửa: {case['outcome']}. "
                "Không suy ra nguyên nhân xe hiện tại từ ca này."),
            "safety": "", "safety_level": "medium", "source_name": "Ca garage đã duyệt",
            "document_version": "", "vehicle_make": case["vehicle_make"],
            "vehicle_model": case["vehicle_model"], "year_from": case["vehicle_year"],
            "year_to": case["vehicle_year"], "engine_code": case["engine_code"],
            "source_url": "", "updated_at": case["published_at"] or case["updated_at"],
            "excerpts": []})
    results.sort(key=lambda case: -(
        (1 / (60 + lexical_rank[case["id"]]) if case["id"] in lexical_rank else 0) +
        (1 / (60 + semantic_rank[case["id"]]) if case["id"] in semantic_rank else 0)))
    return results[:limit]
