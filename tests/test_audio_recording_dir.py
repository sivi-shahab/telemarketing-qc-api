"""Audio upload harus mendarat di WATCH_DIR producer (/data/recording).

Latar: audio yang diunggah lewat menu Upload Audio sebelumnya HANYA masuk bucket
S3, dan enqueue pipeline-nya masih TODO — jadi tidak ada yang memprosesnya.
Yang memproses audio adalah ``/data/script_antrian/producer_watch.py``
(inotify via watchdog) + ``consumer_worker.py``, yang mengawasi ``WATCH_DIR``
(default ``/data/recording``).

Dua kontrak producer yang dijaga test ini:

1. **Tulis-lalu-rename.** ``on_created`` di producer TIDAK mengecek kestabilan
   berkas, jadi menulis langsung ke ``nama.wav`` bisa dipublish saat isinya baru
   separuh. Docstring producer menyebut ``on_moved`` sebagai "pattern atomic
   write dari recorder". Berkas sementara karena itu HARUS memakai akhiran di
   luar ``AUDIO_EXTS`` supaya tidak ikut terdeteksi saat masih ditulis.

2. **Ekstensi.** Producer hanya mengawasi ``.wav/.wave/.mp3``. Format lain yang
   diterima endpoint (m4a, aac, ogg, ...) akan mendarat di folder dan menumpuk
   tanpa pernah diproses, jadi harus ditolak dengan pesan yang jujur.
"""
import pytest

from api.dependencies import Settings


# Ekstensi yang benar-benar diawasi producer (AUDIO_EXTS di producer_watch.py).
PRODUCER_EXTS = {".wav", ".wave", ".mp3"}


def test_settings_punya_audio_recording_dir():
    """Tanpa field ini ``settings.audio_recording_dir`` melempar AttributeError
    di dalam endpoint dan gagalnya menyamar jadi error lain."""
    s = Settings()
    assert hasattr(s, "audio_recording_dir")
    assert s.audio_recording_dir


def test_tulis_atomic_menghasilkan_berkas_utuh(tmp_path):
    from api.routers.transcript import write_audio_to_recording_dir

    isi = b"RIFF" + b"\x00" * 2048
    hasil = write_audio_to_recording_dir(str(tmp_path), "0101003b6O_20260902152537.wav", isi)

    final = tmp_path / "0101003b6O_20260902152537.wav"
    assert hasil == str(final)
    assert final.read_bytes() == isi
    # Tidak menyisakan berkas sementara.
    assert [p.name for p in tmp_path.iterdir()] == [final.name]


def test_berkas_sementara_bukan_ekstensi_audio(tmp_path, monkeypatch):
    """Nama sementara tidak boleh berakhiran .wav/.wave/.mp3 — kalau iya,
    producer akan mempublish berkas yang masih separuh tertulis."""
    from api.routers import transcript as t

    terlihat = []
    asli = t.os.replace

    def rekam(src, dst):
        terlihat.append(str(src))
        return asli(src, dst)

    monkeypatch.setattr(t.os, "replace", rekam)
    t.write_audio_to_recording_dir(str(tmp_path), "a_1.wav", b"x" * 10)

    assert terlihat, "os.replace tidak dipanggil — penulisannya tidak atomic"
    sementara = terlihat[0]
    assert not any(sementara.lower().endswith(e) for e in PRODUCER_EXTS)


def test_ekstensi_di_luar_producer_ditolak():
    """.m4a diterima AUDIO_CONTENT_TYPES tapi tidak diawasi producer."""
    from api.routers.transcript import ensure_vtt_supported_audio

    ensure_vtt_supported_audio("rekaman.wav")   # tidak melempar
    ensure_vtt_supported_audio("rekaman.mp3")

    with pytest.raises(Exception) as exc:
        ensure_vtt_supported_audio("rekaman.m4a")
    pesan = str(getattr(exc.value, "detail", exc.value)).lower()
    assert "m4a" in pesan or "wav" in pesan
