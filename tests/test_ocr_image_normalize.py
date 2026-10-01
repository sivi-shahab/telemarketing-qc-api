"""Normalisasi gambar OCR: semua format raster (+HEIC) -> JPEG/PNG/WEBP.

Butuh ``pillow-heif`` (dependency baru api). Selama image qc-api belum di-build
ulang, perintah test meng-install-nya dulu.
"""
import io

import pytest
from PIL import Image

from api import ocr_image_normalize as n


def _save(img, fmt, **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def _open(page):
    return Image.open(io.BytesIO(page.data))


@pytest.mark.parametrize("fmt,mime,ext", [
    ("PNG", "image/png", ".png"), ("JPEG", "image/jpeg", ".jpg"), ("WEBP", "image/webp", ".webp"),
])
def test_format_web_kecil_disimpan_apa_adanya(fmt, mime, ext):
    raw = _save(Image.new("RGB", (40, 20), "white"), fmt)
    [page] = n.normalize(raw, "a.x", max_pages=10)
    assert (page.data, page.mime_type, page.ext, page.filename) == (raw, mime, ext, "a.x")


@pytest.mark.parametrize("fmt,mode", [
    ("BMP", "RGB"), ("GIF", "P"), ("TIFF", "RGB"), ("AVIF", "RGB"), ("HEIF", "RGB"),
    ("ICO", "RGBA"), ("PPM", "RGB"), ("TGA", "RGB"), ("JPEG2000", "RGB"), ("TIFF", "1"), ("TIFF", "CMYK"),
])
def test_format_lain_jadi_jpeg(fmt, mode):
    # ICO menyimpan beberapa ukuran ikon; minta satu ukuran yang sama dengan gambarnya.
    raw = _save(Image.new(mode, (32, 16)), fmt, **({"sizes": [(32, 16)]} if fmt == "ICO" else {}))
    [page] = n.normalize(raw, "f", max_pages=10)
    assert (page.mime_type, page.ext) == ("image/jpeg", ".jpg")
    im = _open(page)
    assert im.format == "JPEG" and im.size == (32, 16)


def test_tiff_16_bit_jadi_jpeg():
    raw = _save(Image.new("I;16", (8, 8), 40000), "TIFF")
    [page] = n.normalize(raw, "scan.tif", max_pages=10)
    im = _open(page)
    assert im.format == "JPEG" and im.convert("L").getpixel((4, 4)) > 100


def test_png_besar_diperkecil():
    raw = _save(Image.new("RGB", (5000, 100), "white"), "PNG")
    [page] = n.normalize(raw, "lebar.png", max_pages=10)
    assert page.mime_type == "image/jpeg"
    assert _open(page).size == (4096, 82)


def test_transparan_diratakan_ke_putih():
    raw = _save(Image.new("RGBA", (5000, 10), (0, 0, 0, 0)), "PNG")
    [page] = n.normalize(raw, "t.png", max_pages=10)
    r, g, b = _open(page).convert("RGB").getpixel((10, 2))
    assert min(r, g, b) > 240


def test_orientasi_exif_diterapkan_saat_konversi():
    img = Image.new("RGB", (5000, 10), "white")
    exif = img.getexif()
    exif[0x0112] = 6  # rotate 90 CW
    raw = _save(img, "JPEG", exif=exif)
    [page] = n.normalize(raw, "foto.jpg", max_pages=10)
    assert _open(page).size == (8, 4096)


def test_tiff_multi_halaman_dipecah():
    pages = [Image.new("L", (10, 10), v) for v in (0, 128, 255)]
    raw = _save(pages[0], "TIFF", save_all=True, append_images=pages[1:])
    out = n.normalize(raw, "fax.tiff", max_pages=10)
    assert [p.filename for p in out] == ["fax.tiff (hal. 1/3)", "fax.tiff (hal. 2/3)", "fax.tiff (hal. 3/3)"]
    assert [_open(p).convert("L").getpixel((5, 5)) for p in out][0] < 20
    assert _open(out[2]).convert("L").getpixel((5, 5)) > 235


def test_gif_animasi_hanya_frame_pertama():
    frames = [Image.new("P", (10, 10), i) for i in range(4)]
    raw = _save(frames[0], "GIF", save_all=True, append_images=frames[1:])
    assert len(n.normalize(raw, "anim.gif", max_pages=10)) == 1


def test_halaman_melebihi_batas():
    pages = [Image.new("L", (4, 4)) for _ in range(11)]
    raw = _save(pages[0], "TIFF", save_all=True, append_images=pages[1:])
    with pytest.raises(n.TooManyPages) as e:
        n.normalize(raw, "x.tif", max_pages=10)
    assert e.value.pages == 11


@pytest.mark.parametrize("raw", [b"", b"halo dunia", b"%PDF-1.4\n...", b"\x89PNG\r\n\x1a\nrusak"])
def test_bukan_gambar(raw):
    with pytest.raises(n.NotAnImage):
        n.normalize(raw, "a.png", max_pages=10)


def test_nama_panjang_dipotong():
    pages = [Image.new("L", (4, 4)) for _ in range(2)]
    raw = _save(pages[0], "TIFF", save_all=True, append_images=pages[1:])
    out = n.normalize(raw, "x" * 400 + ".tif", max_pages=10)
    assert all(len(p.filename) <= 255 for p in out)
    assert out[0].filename.endswith("(hal. 1/2)")
