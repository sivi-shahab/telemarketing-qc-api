"""Normalisasi gambar menu OCR Gambar.

File apa pun yang terbaca Pillow (plus HEIC/HEIF lewat ``pillow-heif``) diubah
menjadi satu atau beberapa halaman JPEG/PNG/WEBP — satu-satunya bentuk yang
diterima model vision dan bisa ditampilkan browser. Dijalankan API saat upload,
sebelum apa pun disimpan, sehingga worker tidak perlu tahu format asalnya.

TIFF multi-halaman (scan/fax) dipecah per halaman; format lain hanya frame
pertama (GIF/WEBP animasi, MPO kamera). Hasil konversi disimpan JPEG, bukan PNG:
foto HEIC/TIFF besar sebagai PNG bisa melewati batas ukuran request model.
"""
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # image lama tanpa pillow-heif: HEIC ditolak sebagai bukan gambar
    pass

MAX_SIDE = 4096
JPEG_QUALITY = 90
MAX_NAME = 230
_KEEP = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
_SPLIT_FORMATS = {"TIFF"}


class NotAnImage(ValueError):
    """Isi file tidak terbaca sebagai gambar."""


class TooManyPages(ValueError):
    def __init__(self, pages: int):
        super().__init__(f"{pages} halaman")
        self.pages = pages


@dataclass(frozen=True)
class Page:
    filename: str
    data: bytes
    mime_type: str
    ext: str


def normalize(data: bytes, filename: str, max_pages: int) -> list:
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format
        frames = getattr(im, "n_frames", 1)
    except Exception as exc:
        raise NotAnImage(filename) from exc
    count = frames if fmt in _SPLIT_FORMATS else 1
    if count > max_pages:
        raise TooManyPages(count)
    base = (filename or "gambar")[:MAX_NAME]
    pages = []
    for i in range(count):
        try:
            im.seek(i)
            body, mime, ext = _encode(im, data, fmt, single_frame=frames == 1)
        except Exception as exc:
            raise NotAnImage(filename) from exc
        label = base if count == 1 else f"{base} (hal. {i + 1}/{count})"
        pages.append(Page(label, body, mime, ext))
    return pages


def _encode(im, raw, fmt, single_frame):
    if fmt in _KEEP and single_frame and max(im.size) <= MAX_SIDE:
        im.load()  # memastikan isinya benar-benar bisa didekode, bukan hanya header
        mime, ext = _KEEP[fmt]
        return raw, mime, ext
    frame = _to_rgb(ImageOps.exif_transpose(im.copy()))
    frame.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    frame.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue(), "image/jpeg", ".jpg"


def _to_rgb(img):
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    if img.mode.startswith("I;16") or img.mode == "I":
        return img.convert("I").point(lambda v: v * (1 / 256)).convert("L").convert("RGB")
    return img.convert("RGB")
