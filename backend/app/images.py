"""图片处理：读取拍摄时间、转正方向、生成浏览图和缩略图。"""

import io
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

try:  # iPhone 的 HEIC
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

Image.MAX_IMAGE_PIXELS = 120_000_000  # 防止超大图片耗尽内存

VIEW_EDGE = 1600
THUMB_EDGE = 400
FORMAT_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "HEIF": "heic", "MPO": "jpg", "GIF": "gif"}


class InvalidImage(ValueError):
    pass


@dataclass
class Processed:
    original_rel: str
    view_rel: str
    thumb_rel: str
    content_type: str
    width: int
    height: int
    taken_at: datetime
    taken_at_source: str


def _parse_offset(s: str | None) -> timezone | None:
    if not s:
        return None
    s = s.strip()
    try:
        sign = -1 if s[0] == "-" else 1
        hh, mm = s.lstrip("+-").split(":")
        return timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))
    except (ValueError, IndexError):
        return None


def exif_taken_at(img: Image.Image, local_tz) -> datetime | None:
    """EXIF 拍摄时间：DateTimeOriginal → DateTimeDigitized → DateTime。"""
    exif = img.getexif()
    if not exif:
        return None
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    candidates = [
        (sub.get(ExifTags.Base.DateTimeOriginal), sub.get(ExifTags.Base.OffsetTimeOriginal)),
        (sub.get(ExifTags.Base.DateTimeDigitized), sub.get(ExifTags.Base.OffsetTimeDigitized)),
        (exif.get(ExifTags.Base.DateTime), sub.get(ExifTags.Base.OffsetTime)),
    ]
    for value, offset in candidates:
        if not value:
            continue
        try:
            naive = datetime.strptime(str(value).strip().rstrip("\x00"), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
        if naive.year < 2000:  # 相机未设置时间
            continue
        return naive.replace(tzinfo=_parse_offset(offset) or local_tz)
    return None


def _save_jpeg(img: Image.Image, edge: int, quality: int) -> bytes:
    im = img.copy()
    im.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def process_upload(
    data: bytes,
    upload_root: Path,
    local_tz,
    file_mtime: datetime | None,
    now: datetime,
) -> Processed:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise InvalidImage(str(e)) from e
    fmt = img.format or "JPEG"
    ext = FORMAT_EXT.get(fmt)
    if ext is None:
        raise InvalidImage(f"unsupported format {fmt}")

    taken = exif_taken_at(img, local_tz)
    source = "exif"
    if taken is None:
        # 文件修改时间不能晚于现在，也不能早于很久以前
        if file_mtime and now - timedelta(days=3650) < file_mtime <= now + timedelta(minutes=5):
            taken, source = file_mtime, "file"
        else:
            taken, source = now, "upload"

    upright = ImageOps.exif_transpose(img)
    rel_dir = Path(now.strftime("%Y/%m"))
    (upload_root / rel_dir).mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex
    original_rel = rel_dir / f"{stem}.{ext}"
    view_rel = rel_dir / f"{stem}_v.jpg"
    thumb_rel = rel_dir / f"{stem}_t.jpg"
    (upload_root / original_rel).write_bytes(data)
    (upload_root / view_rel).write_bytes(_save_jpeg(upright, VIEW_EDGE, 85))
    (upload_root / thumb_rel).write_bytes(_save_jpeg(upright, THUMB_EDGE, 78))

    return Processed(
        original_rel=original_rel.as_posix(),
        view_rel=view_rel.as_posix(),
        thumb_rel=thumb_rel.as_posix(),
        content_type=Image.MIME.get(fmt, "application/octet-stream"),
        width=upright.width,
        height=upright.height,
        taken_at=taken,
        taken_at_source=source,
    )
