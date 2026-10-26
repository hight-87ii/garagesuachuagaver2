"""Nhập bài triệu chứng tham khảo vào database hiện tại, không sửa bản ghi sẵn có."""

from dotenv import load_dotenv

load_dotenv()

from backend.database import DB_PATH, connect  # noqa: E402
from backend.migrations import run_migrations  # noqa: E402
from backend.technical_starter_data import seed_reference_articles  # noqa: E402


if __name__ == "__main__":
    if not DB_PATH.exists():
        raise SystemExit(f"Chưa có database tại {DB_PATH}; hãy khởi động backend lần đầu trước.")
    with connect() as db:
        run_migrations(db)
        inserted = seed_reference_articles(db)
        total = db.execute("SELECT COUNT(*) FROM technical_articles WHERE status='published'").fetchone()[0]
    print(f"Inserted {inserted} symptom articles; {total} published articles in {DB_PATH}.")
