"""Klien LLM sisi API harus bicara dengan Azure memakai dialek Azure.

Regresi yang dijaga: Upload Campaign dengan RIPLAY PDF gagal dengan

    502 "Ekstraksi RIPLAY gagal dihubungi: Error code: 404 -
        {'error': {'code': '404', 'message': 'Resource not found'}}"

Penyebabnya ``get_llm_client()`` membangun ``OpenAI`` biasa terhadap endpoint Azure
(``*.cognitiveservices.azure.com``). Klien itu menembak ``<base_url>/chat/completions``
— path gaya OpenAI yang di host Azure memang tidak ada, sehingga Azure menjawab 404
"Resource not found". Azure hanya melayani
``/openai/deployments/{deployment}/chat/completions?api-version=...``.

Worker sudah benar sejak lama (``worker/tasks/process_transcript.py:127-139`` memakai
``AzureOpenAI``); sisi API tertinggal karena ``get_llm_client()`` dulu selalu melempar
``AttributeError`` sebelum sempat dipakai, jadi jalur ini belum pernah teruji.

Dampaknya khas: 404 dari penyedia mudah dikira soal kuota/model/jaringan, padahal murni
salah bentuk URL.
"""
import pytest

from api import dependencies as dep


class _Settings:
    """Setting seperlunya untuk membangun klien, meniru nilai produksi."""

    llm_base_url = "https://foundry-dmanalytics-hub.cognitiveservices.azure.com"
    llm_api_key = "kunci-uji"
    llm_model = "gpt-5.4-mini"
    llm_timeout = 1800.0
    llm_api_version = "2025-04-01-preview"
    riplay_model = ""  # kosong = ikut llm_model, sama seperti Settings asli


@pytest.fixture
def fresh_client(monkeypatch):
    """Kosongkan cache klien supaya tiap test membangun ulang dari setting di atas."""
    monkeypatch.setattr(dep, "_llm_client", None)
    monkeypatch.setattr(dep, "get_settings", lambda: _Settings())
    yield
    monkeypatch.setattr(dep, "_llm_client", None)


def test_client_targets_azure_deployment_path(fresh_client):
    """URL tujuan harus path deployment Azure, bukan path gaya OpenAI.

    Ini inti bug-nya: ``base_url`` klien adalah alamat yang benar-benar ditembak, jadi
    memeriksanya berarti memeriksa perilaku, bukan tipe kelas semata.
    """
    url = str(dep.get_llm_client().base_url)
    assert "/openai/deployments/gpt-5.4-mini" in url, (
        f"klien menembak {url!r} — Azure hanya melayani /openai/deployments/<deployment>/"
    )


def test_api_version_is_sent(fresh_client):
    """Tanpa ``api-version`` Azure menolak permintaan; harus ikut terpasang."""
    assert getattr(dep.get_llm_client(), "_api_version", None) == "2025-04-01-preview"


def test_timeout_is_honoured(fresh_client):
    """LLM_TIMEOUT harus diteruskan.

    Bawaan SDK 600 detik per percobaan plus 2 retry; jalur worker pernah kena akibatnya
    (3 percobaan / 1.813 detik untuk satu tiket, 17 September 2026). Ekstraksi RIPLAY
    juga panggilan vision yang lambat, jadi jangan ulangi kesalahan yang sama.
    """
    assert dep.get_llm_client().timeout == 1800.0


def test_settings_declares_llm_api_version():
    """``llm_api_version`` harus ada di Settings, sepadan dengan worker.

    Worker mendeklarasikannya di ``worker/config.py:60`` dengan default yang sama.
    Kalau sisi API tidak punya, ``get_llm_client()`` mengulang persis kegagalan yang
    dijaga ``test_riplay_config.py``: AttributeError yang menyamar jadi 502.
    """
    s = dep.Settings()
    assert hasattr(s, "llm_api_version")
    assert s.llm_api_version == "2025-04-01-preview"


def test_riplay_model_override_drives_the_deployment(monkeypatch):
    """``RIPLAY_MODEL`` harus benar-benar mengganti deployment yang dituju.

    Pada klien Azure, deployment ikut di URL. Kalau klien dibangun dengan
    ``llm_model`` sementara ``_extract_and_gate_riplay`` mengirim ``riplay_model``,
    URL-nya tetap menunjuk model lama dan override itu gagal DIAM-DIAM: tidak ada
    error, hanya model yang salah. Keduanya harus memakai ekspresi yang sama.
    """

    class _Override(_Settings):
        riplay_model = "gpt-5.4-vision"

    monkeypatch.setattr(dep, "_llm_client", None)
    monkeypatch.setattr(dep, "get_settings", lambda: _Override())
    url = str(dep.get_llm_client().base_url)
    monkeypatch.setattr(dep, "_llm_client", None)

    assert "/openai/deployments/gpt-5.4-vision" in url, f"deployment tidak ikut diganti: {url!r}"
