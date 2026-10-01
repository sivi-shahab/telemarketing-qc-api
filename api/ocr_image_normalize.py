"""Normalisasi gambar menu OCR Gambar.

File apa pun yang terbaca Pillow (plus HEIC/HEIF lewat ``pillow-heif``) diubah
menjadi satu atau beberapa halaman JPEG/PNG/WEBP — satu-satunya bentuk yang
diterima model vision dan bisa ditampilkan browser. Dijalankan API saat upload,
sebelum apa pun disimpan, sehingga worker tidak perlu tahu format asalnya.

TIFF multi-halaman (scan/fax) dipecah per halaman; format lain hanya frame
pertama (GIF/WEBP animasi, MPO kamera). Hasil konversi disimpan JPEG, bukan PNG:
foto HEIC/TIFF besar sebagai PNG bisa melewati batas ukuran request model.

Hanya format di ``_ALLOWED_FORMATS`` yang dicoba dibuka (EPS/SVG/vektor dan format
eksotis lain ditolak), dan gambar di atas ``MAX_PIXELS`` ditolak sebelum didekode:
file kecil (PNG terkompresi) bisa berdimensi raksasa dan menghabiskan memori API.
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
MAX_PIXELS = 40_000_000  # 40 megapiksel; jauh di bawah ambang bom dekompresi Pillow
JPEG_QUALITY = 90
MAX_NAME = 230
_KEEP = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
_SPLIT_FORMATS = {"TIFF"}
# ID opener Pillow yang boleh dicoba. MPO (foto kamera) tidak punya opener sendiri:
# dibuka lewat opener JPEG, yang mengembalikan MpoImageFile. Menaruh "MPO" di sini
# justru membuat Image.open() KeyError untuk format setelahnya (HEIF, AVIF, ...).
_ALLOWED_FORMATS = ["JPEG", "PNG", "WEBP", "TIFF", "GIF", "BMP", "HEIF", "AVIF",
                    "JPEG2000", "ICO", "PPM", "TGA"]
_BOMB_ERRORS = (Image.DecompressionBombError, Image.DecompressionBombWarning)


class NotAnImage(ValueError):
    """Isi file tidak terbaca sebagai gambar."""


class TooLarge(ValueError):
    """Resolusi gambar (lebar x tinggi) melewati ``MAX_PIXELS``."""


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
        im = Image.open(io.BytesIO(data), formats=_ALLOWED_FORMATS)
        fmt = im.format
        _check_pixels(im, filename)
        frames = getattr(im, "n_frames", 1)
    except TooLarge:
        raise
    except _BOMB_ERRORS as exc:
        raise TooLarge(filename) from exc
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
            _check_pixels(im, filename)  # tiap halaman TIFF bisa berukuran beda
            body, mime, ext = _encode(im, data, fmt, single_frame=frames == 1)
        except TooLarge:
            raise
        except _BOMB_ERRORS as exc:
            raise TooLarge(filename) from exc
        except Exception as exc:
            raise NotAnImage(filename) from exc
        label = base if count == 1 else f"{base} (hal. {i + 1}/{count})"
        pages.append(Page(label, body, mime, ext))
    return pages


def _check_pixels(im, filename) -> None:
    """Dari header saja (belum didekode): tolak sebelum memori dialokasikan."""
    width, height = im.size
    if width * height > MAX_PIXELS:
        raise TooLarge(filename)


def _encode(im, raw, fmt, single_frame):
    if fmt in _KEEP and single_frame and max(im.size) <= MAX_SIDE:
        im.load()  # memastikan isinya benar-benar bisa didekode, bukan hanya header
        mime, ext = _KEEP[fmt]
        return raw, mime, ext
    if fmt == "JPEG":
        # Dekode langsung pada skala 1/2..1/8 bila jauh di atas MAX_SIDE — hemat memori.
        im.draft("RGB", (MAX_SIDE, MAX_SIDE))
    # exif_transpose selalu mengembalikan gambar baru (hasil transpose, atau salinan
    # bila tanpa orientasi EXIF) yang sudah termuat — frame hasil seek() ikut benar.
    frame = _to_rgb(ImageOps.exif_transpose(im))
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
