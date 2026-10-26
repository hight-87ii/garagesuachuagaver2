"""Hoàn thiện và xuất bản bài kỹ thuật DEMO qua workflow hiện có.

Mặc định chỉ dry-run, không ghi database.

    python -X utf8 publish_demo_technical_articles.py --limit 5
    python -X utf8 publish_demo_technical_articles.py --apply
    python -X utf8 publish_demo_technical_articles.py --review
    python -X utf8 publish_demo_technical_articles.py --publish
    python -X utf8 publish_demo_technical_articles.py --all

`--all` là xác nhận rõ ràng để cập nhật -> duyệt chuyên môn -> xuất bản. Script
không tạo user/token, không ghi SQL trạng thái, và luôn truyền expected_revision.
"""

import argparse
import json
import re
import unicodedata
from collections import Counter

from starlette.requests import Request

from backend.api.v1.technical_knowledge import (
    ArticleIn, publish_article, technical_review, update_article,
)
from backend.database import DB_PATH, connect

DEMO_NOTICE = (
    "NỘI DUNG DEMO DO AI TỔNG HỢP – CHƯA ĐƯỢC ĐỐI CHIẾU VỚI TÀI LIỆU HÃNG. "
    "KHÔNG SỬ DỤNG ĐỂ TỰ SỬA CHỮA HOẶC THAY THẾ CHẨN ĐOÁN CỦA KỸ THUẬT VIÊN."
)
DEMO_SOURCE = "Nội dung demo do AI tổng hợp"
DEMO_VERSION = "Demo, chưa xác minh"
DEMO_REVIEW_NOTE = "Duyệt phục vụ trình diễn hệ thống, không phải duyệt kỹ thuật thực tế"
HEADINGS = (
    "Câu hỏi cần làm rõ", "Khả năng cần phân biệt", "Kiểm tra thực tế",
    "Quy trình kiểm tra theo thứ tự", "Hướng xử lý khi có căn cứ", "An toàn",
    "Phạm vi áp dụng", "Ghi chú giới hạn", "Ghi chú kiểm duyệt demo",
)


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or "").casefold().replace("đ", "d"))
    return "".join(char for char in value if unicodedata.category(char) != "Mn")


def _section(content: str, heading: str) -> str:
    alternatives = "|".join(re.escape(item) for item in HEADINGS if item != heading)
    match = re.search(rf"(?:^|\n){re.escape(heading)}:\s*(.*?)(?=\n\n(?:{alternatives}):|\Z)",
                      content, re.DOTALL)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _scope(row: dict) -> str:
    pieces = []
    if row.get("vehicle_make"):
        pieces.append(f"hãng {row['vehicle_make']}")
    if row.get("vehicle_model"):
        pieces.append(f"dòng {row['vehicle_model']}")
    if row.get("year_from") or row.get("year_to"):
        pieces.append(f"năm {row.get('year_from') or 'không giới hạn'}–{row.get('year_to') or 'hiện tại'}")
    if row.get("engine_code"):
        pieces.append(f"động cơ {row['engine_code']}")
    configured = ", ".join(pieces) if pieces else "xe du lịch có hệ thống và biểu hiện tương ứng"
    return (f"Bản demo định hướng cho {configured}. Với chủ đề “{row['title']}”, phải xác nhận "
            "hãng, dòng xe, năm sản xuất, cấu hình và VIN trước khi áp dụng bất kỳ thao tác nào.")


def _safety(row: dict) -> tuple[str, str]:
    safety = str(row.get("safety") or _section(row["content"], "An toàn") or
                 "Thực hiện kiểm tra tại khu vực phù hợp và dùng trang bị bảo hộ cần thiết.").strip()
    signal = _fold(" ".join((row["title"], row.get("symptoms") or "", safety)))
    hazardous = any(term in signal for term in (
        "phanh", "lai", "tui khi", "srs", "nhien lieu", "cao ap", "hybrid", "nang xe",
        "qua nhiet", "nong may", "chay", "no lop", "ro xang", "mat tro luc",
    ))
    level = row.get("safety_level") or "medium"
    if hazardous and level in ("low", "medium"):
        level = "high"
    if hazardous:
        required = (
            "Dừng vận hành xe nếu có nguy cơ mất an toàn. Không tự tháo sửa nếu không có chuyên môn. "
            "Đưa xe đến cơ sở sửa chữa đủ điều kiện."
        )
        if required not in safety:
            safety = safety.rstrip(". ") + ". " + required
    return safety[:1000], level


def build_demo_item(row: dict) -> ArticleIn:
    questions = _section(row["content"], "Câu hỏi cần làm rõ") or (
        f"Biểu hiện “{row['title']}” bắt đầu khi nào, xuất hiện liên tục hay gián đoạn, "
        "và trước đó xe có sửa chữa hoặc va chạm không?"
    )
    causes = _section(row["content"], "Khả năng cần phân biệt") or (
        f"Có thể có nhiều nhóm nguyên nhân liên quan đến “{row['title']}”; chưa được phép kết luận "
        "chi tiết hỏng nếu chưa tái hiện và đo kiểm trên xe."
    )
    check = (_section(row["content"], "Quy trình kiểm tra theo thứ tự") or
             _section(row["content"], "Kiểm tra thực tế") or
             f"Quan sát hệ thống liên quan đến “{row['title']}” và ghi lại kết quả kiểm tra.")
    check = re.sub(r"\s*Ghi lại điều kiện tái hiện.*$", "", check).strip().rstrip(".")
    action = _section(row["content"], "Hướng xử lý khi có căn cứ") or (
        "Chỉ sửa chữa hoặc thay thế bộ phận sau khi kết quả kiểm tra xác nhận được nguyên nhân."
    )
    safety, level = _safety(row)
    content = (
        f"{DEMO_NOTICE}\n\n"
        f"Câu hỏi cần làm rõ: {questions}\n\n"
        f"Các nguyên nhân có thể cần kiểm tra: {causes}\n\n"
        "Quy trình kiểm tra theo thứ tự:\n"
        f"1. Xác nhận và tái hiện đúng biểu hiện “{row['title']}” trong điều kiện an toàn.\n"
        f"2. {check}.\n"
        "3. Ghi lại dữ liệu, mã lỗi, hình ảnh hoặc kết quả đo thực tế; so sánh hai bên/các trạng thái khi phù hợp.\n"
        "4. Tra tài liệu sửa chữa đúng VIN trước khi tháo, hiệu chuẩn, chọn vật tư hoặc quyết định thay chi tiết.\n\n"
        f"Hướng xử lý có điều kiện: {action} Kỹ thuật viên phải kiểm tra trực tiếp và xác nhận lại trước khi sửa chữa.\n\n"
        f"Cảnh báo an toàn: {safety}\n\n"
        f"Phạm vi áp dụng: {_scope(row)}\n\n"
        f"Ghi chú giới hạn: Bài “{row['title']}” là dữ liệu mẫu phục vụ trình diễn tra cứu/RAG; "
        "không chứa thông số sửa chữa xác nhận theo hãng và không thay thế chẩn đoán thực tế.\n\n"
        f"Ghi chú kiểm duyệt demo: {DEMO_REVIEW_NOTE}."
    )
    return ArticleIn(
        title=row["title"], symptoms=row["symptoms"], content=content, safety=safety,
        source_name=DEMO_SOURCE, source_url="", document_version=DEMO_VERSION,
        vehicle_make=row.get("vehicle_make") or "", vehicle_model=row.get("vehicle_model") or "",
        year_from=row.get("year_from"), year_to=row.get("year_to"),
        engine_code=row.get("engine_code") or "", safety_level=level,
        expected_revision=row["revision"],
    )


def is_complete_demo(row: dict) -> bool:
    content = row.get("content") or ""
    return (row.get("source_name") == DEMO_SOURCE and not row.get("source_url") and
            row.get("document_version") == DEMO_VERSION and DEMO_NOTICE in content and
            all(f"{heading}:" in content for heading in (
                "Câu hỏi cần làm rõ", "Các nguyên nhân có thể cần kiểm tra",
                "Quy trình kiểm tra theo thứ tự", "Hướng xử lý có điều kiện",
                "Cảnh báo an toàn", "Phạm vi áp dụng", "Ghi chú giới hạn")))


def _request(method: str, path: str) -> Request:
    return Request({"type": "http", "method": method, "path": path, "headers": [],
                    "client": ("127.0.0.1", 0), "server": ("localhost", 0), "scheme": "http"})


def _load_rows(mode: str, limit: int | None) -> list[dict]:
    where = "status='draft' AND deleted_at IS NULL"
    params: list[object] = []
    if mode in ("review", "publish"):
        where += " AND source_name=? AND document_version=?"
        params.extend((DEMO_SOURCE, DEMO_VERSION))
    if mode == "publish":
        where += " AND technical_reviewed_by IS NOT NULL"
    sql = f"SELECT * FROM technical_articles WHERE {where} ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"; params.append(limit)
    with connect() as db:
        return [dict(row) for row in db.execute(sql, params)]


def run(*, apply: bool = False, review: bool = False, publish: bool = False,
        all_steps: bool = False, limit: int | None = None) -> dict:
    if not DB_PATH.is_file():
        raise RuntimeError(f"Database không tồn tại: {DB_PATH}")
    if all_steps:
        apply = review = publish = True
    dry_run = not (apply or review or publish)
    mode = "apply" if apply else "review" if review else "publish" if publish else "dry-run"
    rows = _load_rows(mode, limit)
    with connect() as db:
        initial = {row["status"]: row["count"] for row in db.execute(
            "SELECT status,COUNT(*) count FROM technical_articles WHERE deleted_at IS NULL GROUP BY status")}
        users = {row["email"]: dict(row) for row in db.execute(
            "SELECT id,email,role FROM users WHERE email IN ('technician@garage.vn','manager@garage.vn') AND status='active'")}
    if not dry_run and set(users) != {"technician@garage.vn", "manager@garage.vn"}:
        raise RuntimeError("Thiếu tài khoản demo kỹ thuật viên hoặc quản lý đang hoạt động")

    logs, errors = [], []
    counts = Counter()
    for original in rows:
        row = original
        entry = {"id": row["id"], "title": row["title"],
                 "before": {"status": row["status"], "revision": row["revision"]}, "actions": []}
        try:
            candidate = build_demo_item(row)
            if dry_run:
                entry["actions"].append("would_complete_demo_content")
                entry["after"] = {"status": "draft", "revision": row["revision"] + 1,
                                  "safety_level": candidate.safety_level,
                                  "content_chars": len(candidate.content)}
                counts["planned"] += 1
                logs.append(entry)
                continue
            if apply and not is_complete_demo(row):
                row = update_article(row["id"], candidate,
                    _request("PUT", f"/api/v1/ai/technical-articles/{row['id']}"), users["manager@garage.vn"])
                entry["actions"].append("completed")
                counts["completed"] += 1
            elif apply:
                entry["actions"].append("already_complete")
                counts["already_complete"] += 1
            if review and row["technical_reviewed_by"] is None:
                row = technical_review(row["id"],
                    _request("POST", f"/api/v1/ai/technical-articles/{row['id']}/technical-review"),
                    row["revision"], users["technician@garage.vn"])
                entry["actions"].append("technical_reviewed_demo")
                counts["reviewed"] += 1
            elif review:
                entry["actions"].append("already_reviewed")
            if publish:
                if row["technical_reviewed_by"] is None:
                    raise RuntimeError("Bài chưa được duyệt chuyên môn demo")
                row = publish_article(row["id"],
                    _request("POST", f"/api/v1/ai/technical-articles/{row['id']}/publish"),
                    row["revision"], users["manager@garage.vn"])
                entry["actions"].append("published")
                counts["published"] += 1
            entry["after"] = {"status": row["status"], "revision": row["revision"],
                              "technical_reviewed_by": row["technical_reviewed_by"],
                              "reviewed_by": row["reviewed_by"]}
            logs.append(entry)
        except Exception as exc:  # tiếp tục bài khác, nhưng báo đầy đủ bài lỗi
            errors.append({"id": original["id"], "title": original["title"],
                           "error": f"{type(exc).__name__}: {exc}"})

    with connect() as db:
        final = {row["status"]: row["count"] for row in db.execute(
            "SELECT status,COUNT(*) count FROM technical_articles WHERE deleted_at IS NULL GROUP BY status")}
    return {"database": str(DB_PATH), "mode": "dry-run" if dry_run else mode,
            "requested": len(rows), "initial_status": initial, "counts": dict(counts),
            "errors": errors, "final_status": final, "logs": logs}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Hoàn thiện nội dung và nhãn demo")
    parser.add_argument("--review", action="store_true", help="Duyệt chuyên môn demo qua workflow")
    parser.add_argument("--publish", action="store_true", help="Xuất bản các bài demo đã duyệt")
    parser.add_argument("--all", action="store_true", dest="all_steps", help="Xác nhận chạy toàn bộ quy trình")
    parser.add_argument("--limit", type=int, choices=range(1, 10001), metavar="N")
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), ensure_ascii=False, indent=2))
