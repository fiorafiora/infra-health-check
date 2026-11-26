"""Screenshot files live on the data volume, never in git."""

import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import MAX_ATTACHMENTS_PER_TARGET, MAX_UPLOAD_BYTES
from app.models import Attachment

MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(data: bytes) -> str:
    if not data:
        raise ValueError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("The file is larger than 5 MB.")
    mime = sniff_mime(data)
    if mime is None:
        raise ValueError("Only jpg, png, and webp files are accepted.")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("The image could not be read.") from exc
    return mime


def safe_original_name(name: str | None) -> str:
    base = Path(name or "screenshot").name.replace("\x00", "").strip()
    if not base or base in {".", ".."}:
        base = "screenshot"
    return base[:180]


def attachment_path(upload_dir: Path, stored_name: str) -> Path:
    path = (upload_dir / stored_name).resolve()
    if path.parent != upload_dir.resolve():
        raise ValueError("That file path is not valid.")
    return path


def unlink_stored(upload_dir: Path, stored_name: str) -> None:
    try:
        path = attachment_path(upload_dir, stored_name)
    except ValueError:
        return
    if path.is_file():
        path.unlink()


def count_attachments(db: Session, target_type: str, target_id: int) -> int:
    rows = db.scalars(
        select(Attachment.id).where(
            Attachment.target_type == target_type,
            Attachment.target_id == target_id,
        )
    ).all()
    return len(rows)


def save_attachment(
    db: Session,
    upload_dir: Path,
    *,
    client_id: int,
    target_type: str,
    target_id: int,
    original_name: str,
    data: bytes,
    mime: str,
) -> Attachment:
    if count_attachments(db, target_type, target_id) >= MAX_ATTACHMENTS_PER_TARGET:
        raise ValueError(f"Each item can have at most {MAX_ATTACHMENTS_PER_TARGET} screenshots.")
    stored = f"{uuid.uuid4().hex}{MIME_EXT[mime]}"
    attachment_path(upload_dir, stored).write_bytes(data)
    row = Attachment(
        client_id=client_id,
        target_type=target_type,
        target_id=target_id,
        stored_name=stored,
        original_name=safe_original_name(original_name),
        mime=mime,
        size=len(data),
    )
    db.add(row)
    return row


def attachments_for(
    db: Session, client_id: int
) -> dict[tuple[str, int], list[Attachment]]:
    grouped: dict[tuple[str, int], list[Attachment]] = {}
    rows = db.scalars(
        select(Attachment)
        .where(Attachment.client_id == client_id)
        .order_by(Attachment.id)
    ).all()
    for row in rows:
        grouped.setdefault((row.target_type, row.target_id), []).append(row)
    return grouped


def delete_attachment_row(db: Session, upload_dir: Path, row: Attachment) -> None:
    unlink_stored(upload_dir, row.stored_name)
    db.delete(row)


def delete_attachments_for(
    db: Session,
    upload_dir: Path,
    target_type: str,
    target_ids: list[int],
) -> None:
    if not target_ids:
        return
    rows = db.scalars(
        select(Attachment).where(
            Attachment.target_type == target_type,
            Attachment.target_id.in_(target_ids),
        )
    ).all()
    for row in rows:
        delete_attachment_row(db, upload_dir, row)


def thumbnail_bytes(path: Path, max_px: int = 480) -> tuple[bytes, str]:
    with Image.open(path) as image:
        if image.mode in {"RGBA", "LA", "P"}:
            converted = image.convert("RGBA")
            fmt, mime = "PNG", "image/png"
        else:
            converted = image.convert("RGB")
            fmt, mime = "JPEG", "image/jpeg"
        converted.thumbnail((max_px, max_px))
        buffer = BytesIO()
        if fmt == "JPEG":
            converted.save(buffer, format=fmt, quality=82, optimize=True)
        else:
            converted.save(buffer, format=fmt, optimize=True)
        return buffer.getvalue(), mime
