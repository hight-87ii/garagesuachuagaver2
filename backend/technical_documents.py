"""Trích văn bản tài liệu tải lên; không OCR, không chạy macro hoặc nội dung tệp."""

import io
import re
import zipfile
from xml.etree import ElementTree

from .core.errors import BadRequestError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_EXTRACTED_CHARS = 100_000
MAX_PDF_PAGES = 80


def extract_document(filename: str, data: bytes) -> tuple[str, str]:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise BadRequestError("Tài liệu phải có dữ liệu và không vượt quá 5 MB")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "pdf" and data[:1024].lstrip().startswith(b"%PDF-"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise BadRequestError("Máy chủ chưa cài pypdf để đọc PDF") from exc
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted or len(reader.pages) > MAX_PDF_PAGES:
                raise BadRequestError("PDF phải không mã hóa và tối đa 80 trang")
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
                if sum(map(len, pages)) > MAX_EXTRACTED_CHARS:
                    raise BadRequestError("Văn bản PDF vượt quá giới hạn 100.000 ký tự")
            text = "\n\n".join(pages)
        except BadRequestError:
            raise
        except Exception as exc:
            raise BadRequestError("Không đọc được văn bản PDF; kiểm tra tệp hợp lệ") from exc
        mime = "application/pdf"
    elif extension == "docx" and data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_EXTRACTED_CHARS * 8:
                    raise BadRequestError("Nội dung DOCX vượt quá giới hạn")
                xml = archive.read(info)
            if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                raise BadRequestError("DOCX chứa khai báo XML không được phép")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = ["".join(node.itertext()) for node in root.iter(f"{ns}p")]
            text = "\n".join(paragraphs)
        except BadRequestError:
            raise
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError) as exc:
            raise BadRequestError("DOCX không hợp lệ hoặc không có văn bản") from exc
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise BadRequestError("Chỉ nhận PDF hoặc DOCX hợp lệ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 40 or len(text) > MAX_EXTRACTED_CHARS:
        raise BadRequestError("Tài liệu không có đủ văn bản đọc được (không hỗ trợ PDF quét ảnh) hoặc quá dài")
    return text, mime


def split_chunks(text: str, size: int = 850, overlap: int = 100) -> list[str]:
    """Cắt tại ranh giới từ/đoạn gần nhất, giữ chồng lấn ngắn để không đứt ý."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + size // 2, end),
                           text.rfind(". ", start + size // 2, end),
                           text.rfind(" ", start + size // 2, end))
            if boundary > start + size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def index_article_chunks(db, article_id: int, content: str) -> int:
    """Tệp đính kèm nếu có là nguồn đoạn; nếu không thì dùng nội dung bài đã soạn."""
    document = db.execute("SELECT extracted_text FROM technical_documents WHERE article_id=?",
                          (article_id,)).fetchone()
    chunks = split_chunks(document["extracted_text"] if document else content)
    if len(chunks) > 150:
        raise BadRequestError("Tài liệu có quá nhiều đoạn để lập chỉ mục")
    db.execute("DELETE FROM technical_chunks WHERE article_id=?", (article_id,))
    db.executemany("INSERT INTO technical_chunks(article_id,chunk_index,content) VALUES(?,?,?)",
                   [(article_id, index + 1, chunk) for index, chunk in enumerate(chunks)])
    return len(chunks)
