# QC Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambah dua menu read-only — Results Collection dan Transkrip Collection — untuk QC panggilan penagihan berbasis checklist 7 indikator POJK 22/2023, tanpa mengubah alur QC telemarketing yang sudah berjalan.

**Architecture:** Collection diperlakukan sebagai campaign biasa di pipeline yang sudah ada. Sebuah daftar nama campaign di `.env` menjadi satu-satunya penanda; worker memakainya untuk melewati penempelan reference data cashline, dan API memakainya untuk memisahkan tiket collection dari tabel sales. Frontend mendapat satu renderer baru untuk bentuk output checklist.

**Tech Stack:** FastAPI + SQLAlchemy + Celery + pdfplumber (backend), Vue 3 `<script setup>` + vue-router + axios (frontend), pytest (uji backend), `node --test` (uji frontend), Docker Compose.

Spec: `docs/superpowers/specs/2026-08-04-qc-collection-design.md`

## Global Constraints

- **Tidak ada migration, tabel baru, atau bucket baru.**
- **Fitur berikut tidak boleh disentuh:** Statistics (`compliance/stats_aggregate.py`, `views/dashboard/StatsView.vue`), Campaigns, Upload Campaign / Transkrip / Audio, Assign Ticket, Banding, Manual Check.
- **File berikut tidak boleh diubah:** `dashboard/src/components/EvaluationView.vue`, `dashboard/src/views/dashboard/ResultsView.vue`, `dashboard/src/views/dashboard/TranscriptsView.vue`, `compliance/evaluator.py`, `compliance/scoring.py`, `compliance/error_codes.py`.
- **Rilis read-only:** tanpa banding, tanpa manual status, tanpa assign ticket, tanpa statistik untuk collection.
- **Nama variabel lingkungan:** `COLLECTION_CAMPAIGNS` (daftar nama campaign dipisah koma). Default kosong = fitur mati total.
- **Prefiks route wajib `/dashboard/`** — guard di `dashboard/src/router/index.js:100` memulangkan role `qc` dari setiap path yang tidak diawali `/dashboard`.
- **Role yang boleh mengakses:** `qc`, `team_leader_qc`, `qc_support`, `spq_head`, `admin`. Ditegakkan di router backend, bukan hanya di frontend.
- **Bahasa teks antarmuka:** Bahasa Indonesia, konsisten dengan halaman lain.
- **Komentar kode:** Bahasa Indonesia atau Inggris mengikuti berkas yang disunting; docstring Python mengikuti gaya yang ada (deskripsi + alasan, bukan sekadar restatement nama fungsi).

## Perintah uji

**Backend** (pytest tidak terpasang di image; jalankan di container sekali pakai):

```bash
cd /data/scorecard_v2/telemarketing-qc-system
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/ -q"
```

**Baseline sebelum pekerjaan ini dimulai: `21 passed, 6 failed`.** Enam kegagalan itu sudah ada sebelumnya dan **bukan** tanggung jawab plan ini:

- `tests/test_evaluator.py::test_evaluate_direct_json` — `assert 1.0 == 0.0`
- 5 test di `tests/test_pdf_parser.py` yang membutuhkan folder fixture `example_final/transkrip` (tidak ada di repo; masuk `.gitignore`)

Setiap langkah "Expected: PASS" di bawah berarti *test yang baru ditulis* lulus dan jumlah kegagalan tetap 6 — tidak bertambah.

**Frontend** (node 22 tersedia di host; jalur berkas harus eksplisit, bukan folder):

```bash
cd /data/scorecard_v2/telemarketing-qc-system/dashboard
node --test src/views/collection/collectionSummary.test.mjs
```

Baseline `node --test src/views/qc/assignTicketData.test.mjs`: `14 pass, 0 fail`.

## Struktur berkas

| Berkas | Tanggung jawab | Task |
|---|---|---|
| `compliance/campaign_kind.py` *(baru)* | Mengurai `COLLECTION_CAMPAIGNS` dan menjawab "apakah campaign ini collection" | 1 |
| `api/dependencies.py` *(ubah)* | Menyediakan `collection_campaign_set` untuk sisi API | 1 |
| `worker/config.py` *(ubah)* | Menyediakan `collection_campaign_set` untuk sisi worker | 1 |
| `.env.example` *(ubah)* | Mendokumentasikan variabel baru | 1 |
| `compliance/pdf_parser.py` *(ubah)* | Menyimpan gender/emosi per segmen dan meringkasnya jadi metrik per speaker | 2 |
| `worker/tasks/process_transcript.py` *(ubah)* | Melewati reference data cashline untuk collection; menambah `kind` + `speaker_stats` ke JSON hasil | 3 |
| `db/crud.py` *(ubah)* | Filter daftar berdasarkan himpunan nama campaign (masuk / kecuali) | 4 |
| `api/routers/stats.py`, `api/routers/transcript.py` *(ubah)* | Mengecualikan tiket collection dari daftar sales | 4 |
| `compliance/collection_summary.py` *(baru)* | Menurunkan ringkasan checklist dari `result_json` (murni, tanpa DB) | 5 |
| `api/schemas/collection.py` *(baru)* | Bentuk respons daftar collection | 5 |
| `api/routers/collection.py` *(baru)* | Tiga endpoint `/collection/*` + penegakan role | 5 |
| `api/main.py` *(ubah)* | Registrasi router | 5 |
| `dashboard/src/views/collection/collectionSummary.js` *(baru)* | Padanan sisi klien dari peringkas + helper tampilan | 6 |
| `dashboard/src/components/CollectionEvaluationView.vue` *(baru)* | Renderer laporan checklist | 7 |
| `dashboard/src/views/collection/CollectionResultsView.vue` *(baru)* | Daftar + filter + baris expand | 8 |
| `dashboard/src/views/collection/CollectionTranscriptsView.vue` *(baru)* | Daftar PDF transkrip collection | 9 |
| `dashboard/src/router/index.js`, `dashboard/src/components/SidebarMenu.vue` *(ubah)* | Dua route + dua entri menu | 8, 9 |

---

### Task 1: Penanda campaign collection

**Files:**
- Create: `compliance/campaign_kind.py`
- Create: `tests/test_campaign_kind.py`
- Modify: `api/dependencies.py` (blok `class Settings`)
- Modify: `worker/config.py` (blok `class WorkerSettings`)
- Modify: `.env.example`

**Interfaces:**
- Consumes: tidak ada (task pertama)
- Produces:
  - `compliance.campaign_kind.parse_collection_campaigns(raw) -> frozenset[str]`
  - `compliance.campaign_kind.is_collection(name, allowed) -> bool`
  - `api.dependencies.Settings.collection_campaign_set -> frozenset[str]` (property)
  - `worker.config.WorkerSettings.collection_campaign_set -> frozenset[str]` (property)

- [ ] **Step 1: Tulis test yang gagal**

Buat `tests/test_campaign_kind.py`:

```python
"""Unit tests untuk compliance.campaign_kind.

Penanda campaign collection dibaca dari satu variabel lingkungan
(COLLECTION_CAMPAIGNS) oleh API maupun worker, jadi aturan normalisasinya harus
persis sama di kedua sisi — itulah yang dijaga test di berkas ini.
"""
from compliance.campaign_kind import is_collection, parse_collection_campaigns


# --------------------------------------------------------------------------
# parse_collection_campaigns
# --------------------------------------------------------------------------

def test_parse_trims_and_casefolds():
    assert parse_collection_campaigns(" Collection_V2 , KOLEKSI ") == frozenset(
        {"collection_v2", "koleksi"}
    )


def test_parse_drops_empty_entries():
    assert parse_collection_campaigns("a,,  ,b,") == frozenset({"a", "b"})


def test_parse_empty_string_returns_empty_set():
    assert parse_collection_campaigns("") == frozenset()
    assert parse_collection_campaigns("   ") == frozenset()


def test_parse_non_string_returns_empty_set():
    assert parse_collection_campaigns(None) == frozenset()
    assert parse_collection_campaigns(["a"]) == frozenset()


# --------------------------------------------------------------------------
# is_collection
# --------------------------------------------------------------------------

def test_is_collection_matches_case_and_space_insensitively():
    allowed = parse_collection_campaigns("collection_v2")
    assert is_collection("collection_v2", allowed) is True
    assert is_collection("  Collection_V2  ", allowed) is True


def test_is_collection_false_for_other_campaign():
    allowed = parse_collection_campaigns("collection_v2")
    assert is_collection("cashline_mus_v30", allowed) is False


def test_is_collection_false_when_allowed_empty():
    """Default .env kosong berarti fitur mati: tidak ada yang dianggap collection."""
    assert is_collection("collection_v2", frozenset()) is False


def test_is_collection_false_for_missing_name():
    allowed = parse_collection_campaigns("collection_v2")
    assert is_collection(None, allowed) is False
    assert is_collection("", allowed) is False
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_campaign_kind.py -q"
```
Expected: FAIL — `ModuleNotFoundError: No module named 'compliance.campaign_kind'`

- [ ] **Step 3: Tulis implementasi minimal**

Buat `compliance/campaign_kind.py`:

```python
"""Pembeda campaign QC Collection (penagihan) dari campaign sales (cashline).

Satu-satunya sumber kebenaran adalah variabel lingkungan ``COLLECTION_CAMPAIGNS``
— daftar nama campaign dipisah koma. Modul ini dipakai bersama oleh API
(``api/dependencies.py``) dan worker (``worker/config.py``) supaya keduanya
menormalkan dan mencocokkan nama dengan aturan yang sama; kalau tidak, sebuah
tiket bisa dievaluasi sebagai collection tapi tetap muncul di tabel sales.

Nilai default kosong berarti fitur collection mati total: tidak ada campaign yang
dianggap collection dan seluruh perilaku existing tidak berubah. Ini juga
perilaku saat rollback.
"""


def parse_collection_campaigns(raw) -> frozenset:
    """Ubah ``"a, B , ,c"`` menjadi ``frozenset({"a", "b", "c"})``.

    Tiap entri di-trim lalu di-casefold, entri kosong dibuang. Input yang bukan
    string (None, list, dsb.) menghasilkan frozenset kosong — konfigurasi salah
    bentuk mematikan fitur, bukan melempar exception saat startup.
    """
    if not isinstance(raw, str):
        return frozenset()
    return frozenset(part.strip().casefold() for part in raw.split(",") if part.strip())


def is_collection(name, allowed) -> bool:
    """True bila ``name`` (di-trim + casefold) ada di ``allowed``.

    ``allowed`` adalah hasil :func:`parse_collection_campaigns`. Himpunan kosong
    selalu menghasilkan False.
    """
    if not allowed or not isinstance(name, str):
        return False
    return name.strip().casefold() in allowed
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_campaign_kind.py -q"
```
Expected: PASS — `9 passed`

- [ ] **Step 5: Sambungkan ke Settings sisi API**

Di `api/dependencies.py`, tambahkan import setelah blok import yang ada (di bawah `from dotenv import load_dotenv`):

```python
from compliance.campaign_kind import parse_collection_campaigns
```

Di dalam `class Settings`, tambahkan field ini tepat di bawah baris `admin_email: str = os.getenv("ADMIN_EMAIL", "admin@bank.local")`:

```python
    # ============================================
    # QC Collection
    # ============================================
    # Daftar nama campaign penagihan, dipisah koma. Kosong = fitur QC Collection
    # mati dan tidak ada perilaku existing yang berubah.
    collection_campaigns: str = os.getenv("COLLECTION_CAMPAIGNS", "")
```

Dan tambahkan property ini tepat setelah property `database_url` di kelas yang sama:

```python
    @property
    def collection_campaign_set(self) -> frozenset:
        """Nama campaign collection yang sudah dinormalkan (trim + casefold)."""
        return parse_collection_campaigns(self.collection_campaigns)
```

- [ ] **Step 6: Sambungkan ke Settings sisi worker**

Di `worker/config.py`, tambahkan import setelah `from pydantic_settings import BaseSettings`:

```python
from compliance.campaign_kind import parse_collection_campaigns
```

Di dalam `class WorkerSettings`, tambahkan field tepat di bawah `llm_timeout: float = 1800.0`:

```python
    # Daftar nama campaign penagihan, dipisah koma (lihat compliance/campaign_kind.py).
    # Kosong = tidak ada campaign yang diperlakukan sebagai collection.
    collection_campaigns: str = ""
```

Dan tambahkan property ini tepat setelah property `database_url` yang sudah ada di kelas itu:

```python
    @property
    def collection_campaign_set(self) -> frozenset:
        """Nama campaign collection yang sudah dinormalkan (trim + casefold)."""
        return parse_collection_campaigns(self.collection_campaigns)
```

- [ ] **Step 7: Dokumentasikan variabel di `.env.example`**

Tambahkan di akhir `.env.example`:

```
# ============================================
# QC Collection
# ============================================
# Nama campaign penagihan (POJK 22/2023), dipisah koma. Kosong = fitur QC
# Collection mati: tidak ada menu yang berisi data dan perilaku Results /
# Transkrip existing tidak berubah.
COLLECTION_CAMPAIGNS=
```

Catatan: `.env` masuk `.gitignore` (baris pertama) — **jangan** commit `.env`. Isi nilai aslinya secara lokal saat verifikasi manual di Task 3.

- [ ] **Step 8: Verifikasi kedua Settings memuat field baru**

Run:
```bash
docker compose run --rm --no-deps -T api python -c "
from api.dependencies import Settings
from worker.config import WorkerSettings
print('api  :', Settings(collection_campaigns='A, b').collection_campaign_set)
print('worker:', WorkerSettings(collection_campaigns='A, b').collection_campaign_set)
"
```
Expected: dua baris, masing-masing `frozenset({'a', 'b'})` (urutan elemen boleh berbeda)

- [ ] **Step 9: Jalankan seluruh suite**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/ -q"
```
Expected: `30 passed, 6 failed` — 6 kegagalan yang sama seperti baseline, tidak ada yang baru

- [ ] **Step 10: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add compliance/campaign_kind.py tests/test_campaign_kind.py api/dependencies.py worker/config.py .env.example
git commit -m "feat(collection): penanda campaign collection via COLLECTION_CAMPAIGNS"
```

---

### Task 2: Metrik speaker dari transkrip

Header transkrip versi baru berbentuk `AGENT_BM (female) [NETRAL]:` — gender dan emosi sudah tertangkap regex tapi langsung dibuang. Task ini menyimpannya dan meringkasnya jadi metrik per speaker untuk kartu identitas di laporan collection.

**Files:**
- Modify: `compliance/pdf_parser.py:34-36` (regex), `:116-172` (`parse_transcript_pdf`), `:175-188` (helper detik), `:212-248` (`build_transcript`)
- Modify: `tests/test_pdf_parser.py:89` (assertion himpunan key) dan bagian akhir berkas (test baru)

**Interfaces:**
- Consumes: tidak ada dari task sebelumnya
- Produces:
  - `compliance.pdf_parser.speaker_stats(messages: list[dict]) -> list[dict]` — tiap elemen `{"speaker": str, "gender": str|None, "emotions": dict[str, int], "seconds": float, "pct": float}`, urut menurun berdasarkan `seconds`
  - Tiap dict message dari `build_transcript` bertambah dua key: `gender` (`str|None`) dan `emotion` (`str|None`)

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan di akhir `tests/test_pdf_parser.py`:

```python
# --------------------------------------------------------------------------
# speaker_stats — metrik per speaker untuk laporan QC Collection.
# Sengaja murni (bekerja atas list message, bukan PDF) supaya tidak bergantung
# pada folder fixture example_final/transkrip yang tidak ikut di-commit.
# --------------------------------------------------------------------------

from compliance.pdf_parser import _SPEAKER_NAMED_RE, speaker_stats


def _msg(speaker, timestamp, gender=None, emotion=None):
    return {
        "call_index": 1,
        "ticket_id": "T_1",
        "speaker": speaker,
        "timestamp": timestamp,
        "text": "halo",
        "gender": gender,
        "emotion": emotion,
    }


def test_speaker_stats_aggregates_seconds_and_percentage():
    stats = speaker_stats([
        _msg("AGENT_BM", "00:00.00 -> 00:30.00", "female", "NETRAL"),
        _msg("NASABAH", "00:30.00 -> 00:40.00", "male", "NETRAL"),
        _msg("AGENT_BM", "00:40.00 -> 01:00.00", "female", "POSITIF"),
    ])
    assert [s["speaker"] for s in stats] == ["AGENT_BM", "NASABAH"]
    agent, nasabah = stats
    assert agent["seconds"] == 50.0
    assert nasabah["seconds"] == 10.0
    assert agent["pct"] == 83.3
    assert nasabah["pct"] == 16.7
    assert agent["gender"] == "female"
    assert agent["emotions"] == {"NETRAL": 1, "POSITIF": 1}


def test_speaker_stats_handles_legacy_header_without_gender_or_emotion():
    stats = speaker_stats([
        _msg("SPEAKER_0", "00:00.00 -> 00:10.00"),
        _msg("SPEAKER_1", "00:10.00 -> 00:20.00"),
    ])
    assert all(s["gender"] is None for s in stats)
    assert all(s["emotions"] == {} for s in stats)
    assert {s["pct"] for s in stats} == {50.0}


def test_speaker_stats_empty_input():
    assert speaker_stats([]) == []


def test_speaker_stats_zero_duration_does_not_divide_by_zero():
    stats = speaker_stats([_msg("AGENT_BM", "rusak", "female", "NETRAL")])
    assert stats[0]["seconds"] == 0.0
    assert stats[0]["pct"] == 0.0


def test_speaker_named_regex_captures_name_gender_emotion():
    m = _SPEAKER_NAMED_RE.match("AGENT_BM (female) [NETRAL]:")
    assert m is not None
    assert m.group(1) == "AGENT_BM"
    assert m.group(2) == "female"
    assert m.group(3) == "NETRAL"


def test_speaker_named_regex_still_matches_bracket_wrapped_form():
    m = _SPEAKER_NAMED_RE.match("[NASABAH (male) [NETRAL]]:")
    assert m is not None
    assert m.group(1) == "NASABAH"
    assert m.group(2) == "male"
    assert m.group(3) == "NETRAL"
```

Ubah juga assertion himpunan key di `tests/test_pdf_parser.py:89` — `build_transcript` kini menambah dua key:

```python
        assert set(m.keys()) == {
            "call_index", "ticket_id", "speaker", "timestamp", "text",
            "gender", "emotion",
        }
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_pdf_parser.py -q"
```
Expected: FAIL saat pengumpulan berkas — `ImportError: cannot import name 'speaker_stats' from 'compliance.pdf_parser'`

- [ ] **Step 3: Tangkap gender dan emosi di regex**

Di `compliance/pdf_parser.py`, ganti definisi `_SPEAKER_NAMED_RE` (baris 34-36) — grup `(…)` dan `[…]` menjadi capturing group; himpunan string yang cocok tidak berubah:

```python
_SPEAKER_NAMED_RE = re.compile(
    r"^\[?\s*([A-Za-z][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*\[([^\]]*)\]\s*\]?\s*:\s*$"
)
```

Perbarui juga komentar di atasnya agar menyebut ketiga grup:

```python
# A speaker header line (newer upstream format), e.g. "AGENT_BM (female) [NETRAL]:"
# or "[NASABAH (male) [NETRAL]]:" — a named speaker followed by (gender) and
# [emotion], optionally wrapped in outer brackets. Capture groups: 1 = name,
# 2 = gender, 3 = emotion. The (…) and […] groups are kept deliberately loose to
# tolerate gender (male/female) and emotion (NETRAL/POSITIF/NEGATIF) variations.
# Profile lines like "(cid:127) AGENT_BM : ..." don't match (they start with "("
# and carry trailing text after the colon).
```

- [ ] **Step 4: Bawa gender/emosi ke tiap segmen**

Di `parse_transcript_pdf`, tambahkan dua variabel keadaan setelah `current_speaker = None` (baris 131):

```python
    current_gender = None    # dari header bernama; None untuk header legacy
    current_emotion = None
```

Pada cabang `_SPEAKER_RE` (header legacy), reset keduanya — header lama tidak membawa informasi ini:

```python
        if speaker_match:
            current_speaker = f"SPEAKER_{speaker_match.group(1)}"
            current_gender = None
            current_emotion = None
            current = None
            started = True
            continue
```

Pada cabang `_SPEAKER_NAMED_RE`, isi dari grup 2 dan 3:

```python
        named_match = _SPEAKER_NAMED_RE.match(line)
        if named_match:
            current_speaker = named_match.group(1)
            current_gender = (named_match.group(2) or "").strip() or None
            current_emotion = (named_match.group(3) or "").strip() or None
            current = None
            started = True
            continue
```

Dan sertakan pada dict segmen:

```python
            current = {
                "speaker": current_speaker,
                "gender": current_gender,
                "emotion": current_emotion,
                "timestamp": f"{start_ts} -> {end_ts}",
                "text": text.strip(),
            }
```

Perbarui docstring `parse_transcript_pdf` (baris 119-120) agar menyebut key baru:

```python
    Each segment is ``{"speaker": "SPEAKER_n", "gender": str | None,
    "emotion": str | None, "timestamp": "<start> -> <end>", "text": "..."}``.
```

- [ ] **Step 5: Tambahkan helper detik dan `speaker_stats`**

Ganti `_end_timestamp_seconds` (baris 175-188) dengan tiga fungsi berikut — logika lamanya dipertahankan, hanya pemarsingan angka yang di-DRY-kan supaya bisa dipakai ulang oleh perhitungan durasi per segmen:

```python
def _clock_to_seconds(value: str) -> float:
    """Convert an ``MM:SS.ss`` clock string to seconds (``"01:32.81"`` → 92.81).

    Returns ``0.0`` if the value can't be parsed.
    """
    parts = value.strip().split(":")
    try:
        minutes = int(parts[0])
        seconds = float(parts[1])
    except (ValueError, IndexError):
        return 0.0
    return minutes * 60 + seconds


def _end_timestamp_seconds(timestamp: str) -> float:
    """Convert the *end* of a ``"<start> -> <end>"`` segment timestamp to seconds."""
    return _clock_to_seconds(timestamp.split("->")[-1])


def _segment_duration_seconds(timestamp: str) -> float:
    """Length of one ``"<start> -> <end>"`` segment in seconds.

    Returns ``0.0`` for a malformed timestamp or a non-positive span, so a broken
    line can never push a speaker's total negative.
    """
    parts = timestamp.split("->")
    if len(parts) != 2:
        return 0.0
    span = _clock_to_seconds(parts[1]) - _clock_to_seconds(parts[0])
    return span if span > 0 else 0.0
```

Lalu tambahkan `speaker_stats` di akhir berkas, setelah `build_transcript`:

```python
def speaker_stats(messages: list[dict]) -> list[dict]:
    """Per-speaker talk-time / gender / emotion summary for one transcript.

    Feeds the "Identitas panggilan" cards on the QC Collection report, which need
    deterministic facts about who spoke and how long — not an LLM judgement. Input
    is the ``messages`` list from :func:`build_transcript`; nothing is re-parsed.

    Returns one dict per speaker, sorted by ``seconds`` descending::

        [{"speaker": "AGENT_BM", "gender": "female",
          "emotions": {"NETRAL": 12}, "seconds": 92.2, "pct": 70.4}]

    ``gender`` is the first non-empty value seen for that speaker (``None`` for
    the legacy ``[SPEAKER_n]:`` header format, which carries no such data).
    ``emotions`` counts label occurrences. ``pct`` is the share of total spoken
    time across all speakers, ``0.0`` when the total is zero.
    """
    acc: dict[str, dict] = {}
    for msg in messages:
        speaker = msg.get("speaker") or "SPEAKER_?"
        entry = acc.setdefault(
            speaker,
            {"speaker": speaker, "gender": None, "emotions": {}, "seconds": 0.0, "pct": 0.0},
        )
        entry["seconds"] += _segment_duration_seconds(msg.get("timestamp") or "")
        if entry["gender"] is None and msg.get("gender"):
            entry["gender"] = msg["gender"]
        emotion = msg.get("emotion")
        if emotion:
            entry["emotions"][emotion] = entry["emotions"].get(emotion, 0) + 1

    total = sum(e["seconds"] for e in acc.values())
    for entry in acc.values():
        entry["seconds"] = round(entry["seconds"], 1)
        entry["pct"] = round(entry["seconds"] / total * 100, 1) if total else 0.0

    return sorted(acc.values(), key=lambda e: e["seconds"], reverse=True)
```

- [ ] **Step 6: Teruskan key baru lewat `build_transcript`**

Di `build_transcript`, tambahkan dua key pada dict message:

```python
            messages.append(
                {
                    "call_index": call_index,
                    "ticket_id": ticket_id,
                    "speaker": seg["speaker"],
                    "gender": seg.get("gender"),
                    "emotion": seg.get("emotion"),
                    "timestamp": seg["timestamp"],
                    "text": seg["text"],
                }
            )
```

Perbarui docstring `build_transcript` (baris 217-218):

```python
    ``{"call_index", "ticket_id", "speaker", "gender", "emotion", "timestamp",
    "text"}`` and ``call_index`` is 1-based per source file in chronological
    order. ``gender``/``emotion`` are None for the legacy ``[SPEAKER_n]:`` header
    format. ``format_transcript_for_llm`` ignores both, so the text sent to the
    LLM is unchanged.
```

- [ ] **Step 7: Jalankan test, pastikan lulus**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_pdf_parser.py -q"
```
Expected: 6 test baru PASS; 5 kegagalan lama karena fixture PDF hilang tetap ada, tidak bertambah

- [ ] **Step 8: Buktikan input LLM tidak berubah**

Key tambahan tidak boleh bocor ke prompt. Run:
```bash
docker compose run --rm --no-deps -T api python -c "
from compliance.evaluator import format_transcript_for_llm
msgs = [{'call_index':1,'ticket_id':'T_1','speaker':'AGENT_BM','gender':'female',
         'emotion':'NETRAL','timestamp':'00:00.00 -> 00:05.00','text':'halo'}]
out = format_transcript_for_llm(msgs)
assert 'female' not in out and 'NETRAL' not in out, out
print('OK — gender/emosi tidak masuk prompt')
print(out)
"
```
Expected: `OK — gender/emosi tidak masuk prompt`

- [ ] **Step 9: Jalankan seluruh suite**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/ -q"
```
Expected: `36 passed, 6 failed` — 6 kegagalan yang sama seperti baseline

- [ ] **Step 10: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add compliance/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat(parser): simpan gender/emosi per segmen + speaker_stats()"
```

---

### Task 3: Percabangan worker untuk collection

**Files:**
- Modify: `worker/tasks/process_transcript.py:28-36` (import), `:148-199` (langkah 4b–6)
- Create: `tests/test_process_transcript_collection.py`

**Interfaces:**
- Consumes: `compliance.campaign_kind.is_collection`, `worker.config.WorkerSettings.collection_campaign_set` (Task 1); `compliance.pdf_parser.speaker_stats` (Task 2)
- Produces: `result_data.result_json` bertambah dua key — `"kind"` (`"collection"` | `"sales"`) dan `"speaker_stats"` (list dari `speaker_stats`). Untuk collection, `"reference_data"` bernilai `None`.

- [ ] **Step 1: Tulis test yang gagal**

Buat `tests/test_process_transcript_collection.py`:

```python
"""Unit tests untuk percabangan collection di worker.tasks.process_transcript.

Yang dijaga: untuk campaign collection, reference data CASHLINE/CARD HOLDER
TIDAK boleh dibangun maupun ditempel ke scorecard yang dikirim ke LLM. Prompt
collection punya skema output sendiri (checklist 7 indikator) dan data referensi
sales hanya akan mengotorinya — sekaligus membuang satu round-trip ke DWH.

Seluruh I/O (Postgres, MinIO, LLM) diganti fake, jadi test ini murni memeriksa
alur keputusan.
"""
import pytest

from worker.tasks import process_transcript as pt


class _FakeDb:
    def close(self):
        pass


class _FakeResult:
    def __init__(self, campaign):
        self.id = "11111111-1111-1111-1111-111111111111"
        self.campaign = campaign


class _FakeCampaign:
    prompt_text = "PROMPT"
    scorecard_text = "SCORECARD"
    kb_text = "KB"


class _FakeCrud:
    """Pengganti db.crud — mencatat JSON akhir yang disimpan."""

    def __init__(self, result):
        self._result = result
        self.saved = None

    def update_result_status(self, db, result_id, status, **kwargs):
        pass

    def get_result(self, db, result_id):
        return self._result

    def get_active_campaign(self, db, name):
        return _FakeCampaign()

    def save_result_data(self, db, result_id, final_json):
        self.saved = final_json


class _FakeMinio:
    def put_object(self, *args, **kwargs):
        pass


class _FakeSettings:
    minio_bucket_results = "results"
    llm_model = "test-model"
    llm_temperature = 1.0
    llm_seed = 42
    llm_reasoning_effort = "medium"

    def __init__(self, collection_campaign_set):
        self.collection_campaign_set = collection_campaign_set


@pytest.fixture
def harness(monkeypatch):
    """Pasang semua fake; kembalikan fungsi run(campaign, collection_set)."""
    calls = {"reference_built": 0, "scorecard_seen": None}

    def _install(campaign_name, collection_set):
        result = _FakeResult(campaign_name)
        crud = _FakeCrud(result)

        monkeypatch.setattr(pt, "crud", crud)
        monkeypatch.setattr(pt, "_session_factory", lambda: (lambda: _FakeDb()))
        monkeypatch.setattr(pt, "_minio_client", lambda: _FakeMinio())
        monkeypatch.setattr(pt, "_llm_client", lambda: object())
        monkeypatch.setattr(
            pt, "get_worker_settings", lambda: _FakeSettings(collection_set)
        )
        monkeypatch.setattr(pt, "_download_transcripts", lambda rid: ["/tmp/a.pdf"])
        monkeypatch.setattr(
            pt,
            "build_transcript",
            lambda paths: (
                ["a_20260101000000.pdf"],
                [{
                    "call_index": 1, "ticket_id": "a_20260101000000",
                    "speaker": "AGENT_BM", "gender": "female", "emotion": "NETRAL",
                    "timestamp": "00:00.00 -> 00:10.00", "text": "halo",
                }],
                "0m 10s",
            ),
        )
        monkeypatch.setattr(pt, "latest_generated_timestamp", lambda paths: None)
        monkeypatch.setattr(pt, "customer_id_from_filenames", lambda names: "CID1")

        def _fake_reference(customer_id, db):
            calls["reference_built"] += 1
            return "REFERENCE_TEXT", [], {"cust": "x"}

        monkeypatch.setattr(pt, "build_reference_data", _fake_reference)

        def _fake_evaluate(**kwargs):
            calls["scorecard_seen"] = kwargs["scorecard_text"]
            return {"hasil_akhir": "COMPLIANT"}, None

        monkeypatch.setattr(pt, "evaluate", _fake_evaluate)

        pt.process_transcript(str(result.id))
        return crud.saved, calls

    return _install


def test_collection_campaign_skips_reference_data(harness):
    saved, calls = harness("collection_v2", frozenset({"collection_v2"}))
    assert calls["reference_built"] == 0
    assert calls["scorecard_seen"] == "SCORECARD"
    assert saved["kind"] == "collection"
    assert saved["reference_data"] is None


def test_collection_campaign_records_speaker_stats(harness):
    saved, _ = harness("collection_v2", frozenset({"collection_v2"}))
    assert saved["speaker_stats"][0]["speaker"] == "AGENT_BM"
    assert saved["speaker_stats"][0]["gender"] == "female"


def test_sales_campaign_still_appends_reference_data(harness):
    saved, calls = harness("cashline_mus_v30", frozenset({"collection_v2"}))
    assert calls["reference_built"] == 1
    assert calls["scorecard_seen"] == "SCORECARD\n\nREFERENCE_TEXT"
    assert saved["kind"] == "sales"
    assert saved["reference_data"] == {"cust": "x"}


def test_empty_collection_set_treats_everything_as_sales(harness):
    """Default .env kosong: tidak ada perilaku existing yang berubah."""
    saved, calls = harness("collection_v2", frozenset())
    assert calls["reference_built"] == 1
    assert saved["kind"] == "sales"
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_process_transcript_collection.py -q"
```
Expected: FAIL — `KeyError: 'kind'` (dan `reference_built == 1` pada test pertama)

- [ ] **Step 3: Tambahkan import di worker**

Di `worker/tasks/process_transcript.py`, tambahkan dua import setelah `from compliance.evaluator import evaluate` (baris 28):

```python
from compliance.campaign_kind import is_collection
from compliance.pdf_parser import build_transcript, latest_generated_timestamp, speaker_stats
```

(Baris `from compliance.pdf_parser import build_transcript, latest_generated_timestamp` yang lama diganti oleh baris di atas — jangan sampai ada dua import dari modul yang sama.)

- [ ] **Step 4: Cabangkan penyusunan scorecard**

Ganti blok "4b" (baris 153-160) dengan:

```python
        # 4b. Campaign collection (QC penagihan) memakai skema output sendiri —
        # checklist 7 indikator POJK 22/2023, tanpa skor dan tanpa data nasabah.
        # Menempelkan reference data CASHLINE/CARD HOLDER ke prompt-nya hanya
        # mengotori input dan memicu satu lookup DWH yang tidak terpakai.
        is_collection_campaign = is_collection(
            result.campaign, settings.collection_campaign_set
        )
        if is_collection_campaign:
            scorecard_text = campaign.scorecard_text
            reference_raw = None
        else:
            # Bangun CASHLINE + CARD HOLDER reference data dari DB (dicari lewat
            # customer/session id dari prefix nama file PDF paling awal) lalu
            # tempelkan ke scorecard supaya LLM bisa memverifikasinya.
            customer_id = customer_id_from_filenames(sorted_filenames)
            reference_text, ref_warnings, reference_raw = build_reference_data(customer_id, db)
            for warn in ref_warnings:
                logger.warning("reference data (%s / id=%s): %s", result_id, customer_id, warn)
            scorecard_text = f"{campaign.scorecard_text}\n\n{reference_text}"
```

- [ ] **Step 5: Tambahkan `kind` dan `speaker_stats` ke JSON akhir**

Di blok "6. assemble final JSON", tambahkan dua entri tepat setelah `"campaign": result.campaign,`:

```python
            # Penanda skema hasil: "collection" memakai checklist_result (7
            # indikator), "sales" memakai scorecard_result + skor. Disimpan di
            # JSON supaya API/dashboard tidak perlu membaca konfigurasi lagi.
            "kind": "collection" if is_collection_campaign else "sales",
            # Metrik per speaker (durasi bicara, gender, emosi) — dipakai kartu
            # "Identitas panggilan" pada laporan QC Collection.
            "speaker_stats": speaker_stats(messages),
```

- [ ] **Step 6: Jalankan test, pastikan lulus**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_process_transcript_collection.py -q"
```
Expected: PASS — `4 passed`

- [ ] **Step 7: Jalankan seluruh suite**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/ -q"
```
Expected: `40 passed, 6 failed` — 6 kegagalan yang sama seperti baseline

- [ ] **Step 8: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add worker/tasks/process_transcript.py tests/test_process_transcript_collection.py
git commit -m "feat(worker): lewati reference data cashline untuk campaign collection"
```

- [ ] **Step 9: Verifikasi manual end-to-end (sekali, sebelum lanjut)**

Ini satu-satunya titik di mana pipeline sungguhan dijalankan. Langkahnya:

1. Set nilai di `.env` (berkas ini di-gitignore, jangan di-commit):
   ```
   COLLECTION_CAMPAIGNS=collection_v2
   ```
2. Restart api + worker supaya membaca env baru:
   ```bash
   cd /data/scorecard_v2/telemarketing-qc-system
   docker compose up -d --force-recreate api worker
   ```
3. Lewat dashboard, buka **Upload Campaign** dan buat campaign bernama persis `collection_v2` dengan tiga berkas dari folder `campaigns/`:
   - prompt: `prompt_collection_qc_7indikator_v2.txt`
   - knowledge base: `kb_col_v2.txt`
   - scorecard: `scorecard_collection.txt`
4. Lewat dashboard, buka **Upload Transcript**, pilih campaign `collection_v2`, unggah satu PDF transkrip panggilan penagihan.
5. Tunggu status menjadi `done`, lalu periksa JSON hasilnya:
   ```bash
   docker compose exec -T postgres psql -U bankqc -d bankqc -t -c \
     "SELECT jsonb_pretty(result_json #- '{evaluation,checklist_result}')
        FROM result_data ORDER BY id DESC LIMIT 1;"
   ```
   Expected: `"kind": "collection"`, `"reference_data": null`, `"speaker_stats"` terisi, dan `evaluation` memuat `hasil_akhir` + `total_terpenuhi`.
6. Catat nama campaign dan satu `result_id` collection — dipakai untuk verifikasi manual di Task 5 dan Task 8.

Kalau `evaluation` justru berisi `{"error": ...}`, itu guard dari prompt (mis. KB bukan 7 item); periksa kembali berkas yang diunggah di langkah 3 sebelum lanjut.

---

### Task 4: Filter campaign di crud + pengecualian dari daftar sales

**Files:**
- Modify: `db/crud.py:242-311` (`list_results`), `:314-392` (`list_transcripts`)
- Modify: `api/routers/stats.py:10-15` (import), sekitar `:337` (dict `_iso`)
- Modify: `api/routers/transcript.py:415-439` (`list_transcripts`)
- Create: `tests/test_campaign_filters.py`

**Interfaces:**
- Consumes: `Settings.collection_campaign_set` (Task 1)
- Produces:
  - `db.crud.list_results(..., campaigns_in=None, exclude_campaigns=None)`
  - `db.crud.list_transcripts(..., campaigns_in=None, exclude_campaigns=None)`
  - Keduanya menerima `frozenset[str]` berisi nama yang sudah di-casefold; `None` atau himpunan kosong = tanpa filter.

- [ ] **Step 1: Tulis test yang gagal**

Buat `tests/test_campaign_filters.py`:

```python
"""Unit tests untuk filter campaign di crud.list_results / crud.list_transcripts.

Tiket collection punya halaman sendiri dan tidak punya skor maupun AI status;
kalau bocor ke /list_results atau /list_transcripts, barisnya muncul dengan
kolom-kolom kosong dan ikut terhitung pada "Total". Test di sini memeriksa
ekspresi SQL yang terbentuk, bukan sekadar jumlah pemanggilan filter.
"""
from sqlalchemy.dialects import postgresql

from db import crud


class _FakeQuery:
    """Rantai query SQLAlchemy palsu yang mencatat setiap ekspresi filter."""

    def __init__(self, rows, recorder):
        self._rows = rows
        self._recorder = recorder

    def filter(self, expr):
        self._recorder.append(expr)
        return self

    def order_by(self, *a):
        return self

    def offset(self, *a):
        return self

    def limit(self, *a):
        return self

    def count(self):
        return len(self._rows)

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows=()):
        self.filters = []
        self._rows = list(rows)

    def query(self, *a, **k):
        return _FakeQuery(self._rows, self.filters)


def _sql(expr):
    return str(
        expr.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _campaign_filters(db):
    return [_sql(e) for e in db.filters if "campaign" in _sql(e)]


# --------------------------------------------------------------------------
# list_results
# --------------------------------------------------------------------------

def test_list_results_no_campaign_filter_by_default():
    db = _FakeDb()
    crud.list_results(db)
    assert _campaign_filters(db) == []


def test_list_results_exclude_campaigns_builds_negated_in_clause():
    db = _FakeDb()
    crud.list_results(db, exclude_campaigns=frozenset({"collection_v2"}))
    sql = " ".join(_campaign_filters(db))
    assert "collection_v2" in sql
    assert "NOT" in sql.upper()


def test_list_results_campaigns_in_builds_plain_in_clause():
    db = _FakeDb()
    crud.list_results(db, campaigns_in=frozenset({"collection_v2"}))
    sql = " ".join(_campaign_filters(db))
    assert "collection_v2" in sql
    assert "NOT" not in sql.upper()


def test_list_results_empty_set_is_treated_as_no_filter():
    db = _FakeDb()
    crud.list_results(db, exclude_campaigns=frozenset(), campaigns_in=frozenset())
    assert _campaign_filters(db) == []


# --------------------------------------------------------------------------
# list_transcripts
# --------------------------------------------------------------------------

def test_list_transcripts_exclude_campaigns_builds_negated_in_clause():
    db = _FakeDb()
    crud.list_transcripts(db, exclude_campaigns=frozenset({"collection_v2"}))
    sql = " ".join(_campaign_filters(db))
    assert "collection_v2" in sql
    assert "NOT" in sql.upper()


def test_list_transcripts_campaigns_in_builds_plain_in_clause():
    db = _FakeDb()
    crud.list_transcripts(db, campaigns_in=frozenset({"collection_v2"}))
    sql = " ".join(_campaign_filters(db))
    assert "collection_v2" in sql
    assert "NOT" not in sql.upper()
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_campaign_filters.py -q"
```
Expected: FAIL — `TypeError: list_results() got an unexpected keyword argument 'exclude_campaigns'`

- [ ] **Step 3: Tambahkan parameter di `crud.list_results`**

Di `db/crud.py`, tambahkan dua parameter pada signature `list_results` (setelah `campaign: Optional[str] = None,`):

```python
    campaigns_in: Optional[frozenset] = None,
    exclude_campaigns: Optional[frozenset] = None,
```

Lalu tambahkan blok filter tepat setelah `if campaign: q = q.filter(Result.campaign == campaign)`:

```python
    # ``campaigns_in`` / ``exclude_campaigns`` memisahkan tiket QC Collection dari
    # tiket sales: halaman Collection memakai yang pertama, tabel Results sales
    # memakai yang kedua. Isinya nama campaign yang sudah di-casefold (lihat
    # compliance/campaign_kind.py), jadi pembandingannya dilakukan atas
    # lower(trim(campaign)). Himpunan kosong = tanpa filter.
    if campaigns_in:
        q = q.filter(func.lower(func.trim(Result.campaign)).in_(sorted(campaigns_in)))
    if exclude_campaigns:
        q = q.filter(
            (Result.campaign.is_(None))
            | (~func.lower(func.trim(Result.campaign)).in_(sorted(exclude_campaigns)))
        )
```

Perbarui juga komentar penjelas di awal fungsi (setelah baris tentang `uploaded_by_username`) dengan satu kalimat:

```python
    # ``campaigns_in`` / ``exclude_campaigns`` memisahkan tiket QC Collection dari
    # tiket sales (lihat blok filter di bawah).
```

- [ ] **Step 4: Tambahkan parameter yang sama di `crud.list_transcripts`**

Tambahkan dua parameter pada signature `list_transcripts` (setelah `campaign: Optional[str] = None,`):

```python
    campaigns_in: Optional[frozenset] = None,
    exclude_campaigns: Optional[frozenset] = None,
```

Dan blok filter yang sama tepat setelah `if campaign: q = q.filter(Result.campaign == campaign)` di fungsi itu:

```python
    # Sama seperti list_results: memisahkan transkrip QC Collection dari transkrip
    # sales. Himpunan kosong = tanpa filter.
    if campaigns_in:
        q = q.filter(func.lower(func.trim(Result.campaign)).in_(sorted(campaigns_in)))
    if exclude_campaigns:
        q = q.filter(
            (Result.campaign.is_(None))
            | (~func.lower(func.trim(Result.campaign)).in_(sorted(exclude_campaigns)))
        )
```

- [ ] **Step 5: Jalankan test, pastikan lulus**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_campaign_filters.py -q"
```
Expected: PASS — `6 passed`

- [ ] **Step 6: Kecualikan tiket collection dari `/list_results`**

Di `api/routers/stats.py`, tambahkan `get_settings` ke daftar import dari `api.dependencies` (baris 10-15):

```python
from api.dependencies import (
    get_current_user,
    get_db,
    get_settings,
    get_spq_head_user,
    get_tl_qc_or_spq_head_user,
)
```

Di dalam fungsi `list_results`, sisipkan satu baris **setelah** blok `if role == "team_leader_qc":` selesai dan **sebelum** baris `ai_filter = ...`. Penempatan ini penting: blok Team Leader QC bisa mengganti `_iso` seluruhnya, jadi penambahan harus terjadi sesudahnya.

```python
    # Tiket QC Collection punya halaman sendiri (/collection/list_results) dan
    # tidak punya skor / AI status / error code — jangan tampilkan di tabel
    # Results sales, di mana barisnya hanya akan tampil kosong dan ikut menaikkan
    # angka "Total".
    _iso["exclude_campaigns"] = get_settings().collection_campaign_set
```

`_iso` sudah di-spread sebagai `**_iso` ke keempat pemanggilan `crud.list_results` di fungsi ini, jadi tidak ada perubahan lain yang diperlukan.

- [ ] **Step 7: Kecualikan transkrip collection dari `/list_transcripts`**

Di `api/routers/transcript.py`, fungsi `list_transcripts`, sisipkan satu baris setelah dict `iso` dibentuk dan sebelum pemanggilan `crud.list_transcripts`:

```python
    # Transkrip QC Collection punya halaman sendiri (/collection/list_transcripts).
    iso["exclude_campaigns"] = get_settings().collection_campaign_set
```

`get_settings` sudah diimpor di berkas ini.

- [ ] **Step 8: Verifikasi API masih menyala**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system
docker compose up -d --force-recreate api && sleep 8 && curl -sf http://localhost:4000/health && echo " OK"
```
Expected: respons health check diikuti ` OK`

- [ ] **Step 9: Jalankan seluruh suite**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/ -q"
```
Expected: `46 passed, 6 failed` — 6 kegagalan yang sama seperti baseline

- [ ] **Step 10: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add db/crud.py api/routers/stats.py api/routers/transcript.py tests/test_campaign_filters.py
git commit -m "feat(api): filter campaign di daftar + kecualikan collection dari tabel sales"
```

---

### Task 5: Endpoint `/collection/*`

**Files:**
- Create: `compliance/collection_summary.py`
- Create: `tests/test_collection_summary.py`
- Create: `api/schemas/collection.py`
- Create: `api/routers/collection.py`
- Modify: `api/main.py:7` (import), `:36-48` (registrasi router)

**Interfaces:**
- Consumes: `crud.list_results(campaigns_in=...)`, `crud.list_transcripts(campaigns_in=...)` (Task 4); `Settings.collection_campaign_set` (Task 1)
- Produces:
  - `compliance.collection_summary.summarize_collection(result_json) -> dict` dengan key `hasil_akhir`, `total_terpenuhi`, `total_dinilai`, `failed_indicators`, `deskcoll_name`, `cardholder_name`, `error`
  - `GET /collection/list_results` → `CollectionResultListResponse`
  - `GET /collection/list_transcripts` → `TranscriptListResponse` (dipakai ulang dari `api/schemas/result.py`)
  - `GET /collection/result/{result_id}` → `ResultResponse` (dipakai ulang)

- [ ] **Step 1: Tulis test yang gagal untuk peringkas**

Buat `tests/test_collection_summary.py`:

```python
"""Unit tests untuk compliance.collection_summary.

Peringkas ini mengubah result_json menjadi baris tabel Results Collection.
Kontraknya: JSON yang cacat tidak boleh melempar exception — barisnya tetap
tampil dengan pesan di field ``error``, karena tiket yang gagal dievaluasi justru
yang paling perlu terlihat oleh QC.
"""
from compliance.collection_summary import summarize_collection


def _result_json(**evaluation):
    return {"kind": "collection", "evaluation": evaluation}


def test_summarize_compliant_result():
    s = summarize_collection(_result_json(
        deskcoll_name="Ibu Tiwi",
        cardholder_name="Ferdianus Rigi",
        hasil_akhir="COMPLIANT",
        total_terpenuhi=7,
        total_dinilai=7,
        checklist_result=[{"no": i, "status": "YA"} for i in range(1, 8)],
    ))
    assert s["hasil_akhir"] == "COMPLIANT"
    assert s["total_terpenuhi"] == 7
    assert s["failed_indicators"] == []
    assert s["deskcoll_name"] == "Ibu Tiwi"
    assert s["error"] is None


def test_summarize_collects_failed_indicator_numbers_in_order():
    s = summarize_collection(_result_json(
        hasil_akhir="TIDAK COMPLIANT",
        total_terpenuhi=5,
        total_dinilai=7,
        checklist_result=[
            {"no": 4, "status": "TIDAK"},
            {"no": 1, "status": "YA"},
            {"no": 2, "status": "tidak"},
        ],
    ))
    assert s["failed_indicators"] == [2, 4]


def test_summarize_reports_model_error_payload():
    s = summarize_collection({"evaluation": {"error": "kb must contain exactly 7 items, got 5"}})
    assert s["error"] == "kb must contain exactly 7 items, got 5"
    assert s["hasil_akhir"] is None


def test_summarize_missing_checklist_is_an_error_not_a_crash():
    s = summarize_collection({"evaluation": {"hasil_akhir": "COMPLIANT"}})
    assert s["error"] is not None
    assert s["failed_indicators"] == []


def test_summarize_handles_none_and_wrong_shapes():
    for bad in (None, {}, {"evaluation": None}, {"evaluation": []}, "bukan dict"):
        s = summarize_collection(bad)
        assert s["error"] is not None
        assert s["failed_indicators"] == []


def test_summarize_ignores_checklist_items_without_usable_number():
    s = summarize_collection(_result_json(
        checklist_result=[
            {"no": "3", "status": "TIDAK"},
            {"no": None, "status": "TIDAK"},
            {"status": "TIDAK"},
            "bukan dict",
        ],
    ))
    assert s["failed_indicators"] == [3]
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_collection_summary.py -q"
```
Expected: FAIL — `ModuleNotFoundError: No module named 'compliance.collection_summary'`

- [ ] **Step 3: Tulis peringkas**

Buat `compliance/collection_summary.py`:

```python
"""Ringkasan satu baris untuk hasil QC Collection.

Mengubah ``result_data.result_json`` menjadi angka-angka yang ditampilkan tabel
Results Collection: hasil akhir, jumlah indikator terpenuhi, dan nomor indikator
yang gagal.

Aturan utamanya: JSON yang cacat TIDAK melempar exception. Output LLM bisa
mengembalikan ``{"error": ...}`` (guard bawaan prompt) atau bentuk yang tidak
dikenali, dan justru tiket seperti itulah yang paling perlu terlihat oleh QC —
jadi kegagalan dilaporkan lewat field ``error``, bukan lewat baris yang hilang
atau endpoint yang 500.
"""

_EMPTY = {
    "hasil_akhir": None,
    "total_terpenuhi": None,
    "total_dinilai": None,
    "failed_indicators": [],
    "deskcoll_name": None,
    "cardholder_name": None,
    "error": None,
}


def _blank(error):
    out = dict(_EMPTY)
    out["error"] = error
    return out


def _as_int(value):
    """Coerce ke int bila memungkinkan, else None (``"3"`` → 3, ``None`` → None)."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize_collection(result_json) -> dict:
    """Ringkas ``result_json`` sebuah tiket collection.

    Mengembalikan dict dengan key: ``hasil_akhir``, ``total_terpenuhi``,
    ``total_dinilai``, ``failed_indicators`` (nomor indikator berstatus TIDAK,
    urut menaik), ``deskcoll_name``, ``cardholder_name``, dan ``error``
    (None bila ringkasan berhasil dibaca).
    """
    if not isinstance(result_json, dict):
        return _blank("Hasil evaluasi tidak tersedia.")

    evaluation = result_json.get("evaluation")
    if not isinstance(evaluation, dict):
        return _blank("Hasil evaluasi tidak tersedia.")

    if evaluation.get("error"):
        return _blank(str(evaluation["error"]))

    items = evaluation.get("checklist_result")
    if not isinstance(items, list):
        return _blank("Hasil checklist tidak ditemukan pada evaluasi.")

    failed = sorted(
        no
        for item in items
        if isinstance(item, dict)
        and str(item.get("status") or "").strip().upper() == "TIDAK"
        and (no := _as_int(item.get("no"))) is not None
    )

    return {
        "hasil_akhir": evaluation.get("hasil_akhir"),
        "total_terpenuhi": _as_int(evaluation.get("total_terpenuhi")),
        "total_dinilai": _as_int(evaluation.get("total_dinilai")),
        "failed_indicators": failed,
        "deskcoll_name": evaluation.get("deskcoll_name"),
        "cardholder_name": evaluation.get("cardholder_name"),
        "error": None,
    }
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/test_collection_summary.py -q"
```
Expected: PASS — `6 passed`

- [ ] **Step 5: Commit peringkas**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add compliance/collection_summary.py tests/test_collection_summary.py
git commit -m "feat(collection): peringkas hasil checklist dari result_json"
```

- [ ] **Step 6: Tulis skema respons**

Buat `api/schemas/collection.py`:

```python
"""Bentuk respons untuk endpoint QC Collection.

Sengaja terpisah dari ``api/schemas/result.py``: hasil collection adalah
checklist YA/TIDAK tanpa skor, sehingga tidak punya ``ai_score``,
``passing_grade``, maupun ``maximum_score`` seperti ``ResultListItem``.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CollectionResultItem(BaseModel):
    result_id: str
    id: Optional[str] = None  # ticket id = prefix sebelum "_" pada nama file pertama
    campaign: Optional[str] = None
    status: str  # pending | processing | done | failed
    num_calls: Optional[int] = None
    audio_duration: Optional[str] = None  # total durasi bicara, mis. "2m 11s"
    uploaded_at: Optional[datetime] = None
    generated_at: Optional[datetime] = None  # tanggal transkrip dari header PDF
    completed_at: Optional[datetime] = None
    deskcoll_name: Optional[str] = None
    cardholder_name: Optional[str] = None
    hasil_akhir: Optional[str] = None  # COMPLIANT | TIDAK COMPLIANT
    total_terpenuhi: Optional[int] = None
    total_dinilai: Optional[int] = None
    failed_indicators: list[int] = []  # nomor indikator berstatus TIDAK
    error: Optional[str] = None  # evaluasi gagal dibaca / status failed

    class Config:
        from_attributes = True


class CollectionResultListResponse(BaseModel):
    items: list[CollectionResultItem]
    total: int
    page: int
    limit: int
```

- [ ] **Step 7: Tulis router**

Buat `api/routers/collection.py`:

```python
"""QC Collection — daftar hasil & transkrip untuk campaign penagihan.

Read-only. Tiket collection dievaluasi oleh pipeline yang sama dengan tiket
sales, tetapi memakai skema output sendiri (checklist 7 indikator POJK 22/2023,
tanpa skor), sehingga tidak bisa memakai ``/list_results`` maupun
``/result/{id}`` yang menempelkan tabel Error Code khusus cashline.

Campaign mana yang termasuk collection ditentukan oleh ``COLLECTION_CAMPAIGNS``
(lihat ``compliance/campaign_kind.py``). Bila kosong, seluruh endpoint di sini
mengembalikan daftar kosong.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db, get_settings
from api.schemas.collection import (
    CollectionResultItem,
    CollectionResultListResponse,
)
from api.schemas.result import ResultResponse, TranscriptListResponse
from compliance.collection_summary import summarize_collection
# Dipakai bersama /list_results supaya batas tanggal (WIB, generated_at dengan
# fallback uploaded_at) punya arti yang persis sama di kedua halaman.
from compliance.stats_aggregate import _parse_ymd
from db import crud

router = APIRouter(prefix="/collection", tags=["collection"])

# Sama dengan menu Transkrip (Recording Tickets).
_ALLOWED_ROLES = ("qc", "team_leader_qc", "qc_support", "spq_head", "admin")

# Batas atas saat hasil harus disaring di Python sebelum dipaginasi.
_ALL_ROWS = 1_000_000


def _require_collection_role(current_user=Depends(get_current_user)):
    if getattr(current_user, "role", None) not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak"
        )
    return current_user


def _collection_set():
    return get_settings().collection_campaign_set


def _customer_id_from_files(source_files) -> Optional[str]:
    """Ticket id = prefix sebelum ``_`` pada nama file pertama (sama dengan Results)."""
    if not source_files:
        return None
    first = source_files[0]
    if not isinstance(first, str) or not first:
        return None
    return first.split("_", 1)[0]


def _build_item(result, result_json) -> CollectionResultItem:
    summary = summarize_collection(result_json) if result.status == "done" else dict(
        hasil_akhir=None, total_terpenuhi=None, total_dinilai=None,
        failed_indicators=[], deskcoll_name=None, cardholder_name=None, error=None,
    )
    audio_duration = None
    if isinstance(result_json, dict):
        audio_duration = result_json.get("audio_duration")
    return CollectionResultItem(
        result_id=str(result.id),
        id=_customer_id_from_files(result.source_files),
        campaign=result.campaign,
        status=result.status,
        num_calls=result.num_calls,
        audio_duration=audio_duration,
        uploaded_at=result.uploaded_at,
        generated_at=result.generated_at,
        completed_at=result.completed_at,
        error=result.error_message if result.status == "failed" else summary["error"],
        **{k: summary[k] for k in (
            "deskcoll_name", "cardholder_name", "hasil_akhir",
            "total_terpenuhi", "total_dinilai", "failed_indicators",
        )},
    )


def _matches_hasil(item: CollectionResultItem, wanted: str) -> bool:
    """Cocokkan filter hasil; "TIDAK_COMPLIANT" dinormalkan ke "TIDAK COMPLIANT"."""
    actual = (item.hasil_akhir or "").strip().upper()
    return actual == wanted.strip().upper().replace("_", " ")


@router.get("/list_results", response_model=CollectionResultListResponse)
def list_collection_results(
    ticket_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    hasil: Optional[str] = Query(
        None, description="COMPLIANT | TIDAK_COMPLIANT"
    ),
    date_start: Optional[str] = Query(None, description="YYYY-MM-DD (WIB)"),
    date_end: Optional[str] = Query(None, description="YYYY-MM-DD (WIB)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(_require_collection_role),
):
    """Daftar tiket QC Collection, terbaru dulu."""
    campaigns = _collection_set()
    if not campaigns:
        return CollectionResultListResponse(items=[], total=0, page=page, limit=limit)

    common = dict(
        campaigns_in=campaigns,
        status=status_filter,
        ticket_id=ticket_id,
        date_start=_parse_ymd(date_start),
        date_end=_parse_ymd(date_end),
    )

    if hasil:
        # "hasil" diturunkan dari result_json (tidak tersimpan sebagai kolom), jadi
        # muat seluruh himpunan yang cocok, saring di Python, lalu paginasi —
        # pola yang sama dipakai filter ai_status di /list_results.
        rows, _ = crud.list_results(db, page=1, limit=_ALL_ROWS, **common)
        json_map = crud.result_json_map(db, [str(r.id) for r in rows])
        items = [_build_item(r, json_map.get(str(r.id))) for r in rows]
        items = [it for it in items if _matches_hasil(it, hasil)]
        total = len(items)
        items = items[(page - 1) * limit : page * limit]
    else:
        rows, total = crud.list_results(db, page=page, limit=limit, **common)
        json_map = crud.result_json_map(db, [str(r.id) for r in rows])
        items = [_build_item(r, json_map.get(str(r.id))) for r in rows]

    return CollectionResultListResponse(
        items=items, total=total, page=page, limit=limit
    )


@router.get("/list_transcripts", response_model=TranscriptListResponse)
def list_collection_transcripts(
    ticket_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(_require_collection_role),
):
    """Satu baris per PDF transkrip milik campaign collection."""
    campaigns = _collection_set()
    if not campaigns:
        return TranscriptListResponse(items=[], total=0, page=page, limit=limit)

    items, total = crud.list_transcripts(
        db,
        campaigns_in=campaigns,
        status=status_filter,
        ticket_id=ticket_id,
        page=page,
        limit=limit,
    )
    return TranscriptListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/result/{result_id}", response_model=ResultResponse)
def get_collection_result(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(_require_collection_role),
):
    """Detail satu tiket collection — ``result_json`` apa adanya.

    Berbeda dari ``GET /result/{id}``, tidak ada penempelan tabel Error Code:
    tabel itu dibangun dari item scorecard ``SC_CL_*`` yang tidak ada pada hasil
    collection.
    """
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Result tidak ditemukan"
        )
    if result.campaign is None or result.campaign.strip().casefold() not in _collection_set():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result ini bukan tiket QC Collection",
        )

    if result.status == "done":
        data = crud.get_result_data(db, result_id)
        return ResultResponse(
            result_id=result_id,
            status=result.status,
            result=data.result_json if data else None,
        )
    if result.status == "failed":
        return ResultResponse(
            result_id=result_id, status=result.status, error=result.error_message
        )
    return ResultResponse(result_id=result_id, status=result.status)
```

- [ ] **Step 8: Daftarkan router**

Di `api/main.py`, tambahkan `collection` ke daftar import baris 7:

```python
from api.routers import agent_error, auth, campaign, collection, document, error_code_appeal, qc_assignment, qc_database, qc_manual_check, qc_status, sales_database, stats, transcript, webhook
```

Dan tambahkan registrasinya setelah `app.include_router(sales_database.router)`:

```python
app.include_router(collection.router)
```

- [ ] **Step 9: Verifikasi router terpasang**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system
docker compose up -d --force-recreate api && sleep 8
curl -sf http://localhost:4000/openapi.json | python3 -c "
import json,sys
paths = sorted(p for p in json.load(sys.stdin)['paths'] if p.startswith('/collection'))
print('\n'.join(paths))
"
```
Expected: tiga baris — `/collection/list_results`, `/collection/list_transcripts`, `/collection/result/{result_id}`

- [ ] **Step 10: Verifikasi manual dengan data sungguhan**

Pakai `result_id` collection yang dicatat pada Task 3 Step 9. Ambil token dengan login lewat dashboard lalu salin `access_token` dari localStorage, atau pakai endpoint login:

```bash
TOKEN=$(curl -s -X POST http://localhost:4000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:4000/collection/list_results?limit=5' | python3 -m json.tool | head -30
```
Expected: `items` memuat tiket collection dengan `hasil_akhir`, `total_terpenuhi`, dan `failed_indicators` terisi.

Lalu pastikan tiket itu **tidak** muncul di daftar sales:
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:4000/list_results?limit=100' \
  | python3 -c "
import json,sys
items = json.load(sys.stdin)['items']
bad = [i['id'] for i in items if (i.get('campaign') or '').lower() == 'collection_v2']
print('BOCOR:', bad) if bad else print('OK — tidak ada tiket collection di /list_results')
"
```
Expected: `OK — tidak ada tiket collection di /list_results`

- [ ] **Step 11: Jalankan seluruh suite**

Run:
```bash
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/ -q"
```
Expected: `52 passed, 6 failed` — 6 kegagalan yang sama seperti baseline

- [ ] **Step 12: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add api/schemas/collection.py api/routers/collection.py api/main.py
git commit -m "feat(api): endpoint /collection untuk daftar hasil, transkrip, dan detail"
```

---

### Task 6: Helper ringkasan sisi klien

**Files:**
- Create: `dashboard/src/views/collection/collectionSummary.js`
- Create: `dashboard/src/views/collection/collectionSummary.test.mjs`

**Interfaces:**
- Consumes: bentuk `result_json` dari `GET /collection/result/{id}` (Task 5)
- Produces:
  - `summarizeCollection(resultJson) -> {hasilAkhir, isCompliant, totalTerpenuhi, totalDinilai, failedIndicators, deskcollName, cardholderName, ringkasan, error}`
  - `checklistItems(resultJson) -> Array<{no, kbCode, indikator, pasal, status, isPass, catatan, quote, timestamp}>` (urut `no` menaik)
  - `speakerCards(resultJson) -> Array<{speaker, gender, dominantEmotion, seconds, pct}>`
  - `formatSeconds(seconds) -> string` (mis. `92.2` → `"1m 32s"`)

- [ ] **Step 1: Tulis test yang gagal**

Buat `dashboard/src/views/collection/collectionSummary.test.mjs`:

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  summarizeCollection,
  checklistItems,
  speakerCards,
  formatSeconds,
} from './collectionSummary.js'

const OK_JSON = {
  kind: 'collection',
  audio_duration: '2m 11s',
  speaker_stats: [
    { speaker: 'AGENT_BM', gender: 'female', emotions: { NETRAL: 12 }, seconds: 92.2, pct: 70.4 },
    { speaker: 'NASABAH', gender: 'male', emotions: {}, seconds: 20.4, pct: 15.6 },
  ],
  evaluation: {
    deskcoll_name: 'Ibu Tiwi',
    cardholder_name: 'Ferdianus Rigi',
    hasil_akhir: 'TIDAK COMPLIANT',
    total_terpenuhi: 6,
    total_dinilai: 7,
    ringkasan: 'Enam dari tujuh indikator terpenuhi.',
    checklist_result: [
      { no: 2, kb_code: 'KB_COL_2', indikator: 'Perkenalan?', pasal: 'Pasal 4 ayat (1)',
        status: 'TIDAK', catatan: 'Institusi tidak disebut.',
        evidence: { timestamp: '00:56', quote: 'saya dengan Ibu Tiwi' } },
      { no: 1, kb_code: 'KB_COL_1', indikator: 'Salam?', pasal: 'Pasal 4 ayat (1)',
        status: 'YA', catatan: 'Salam diucapkan.',
        evidence: { timestamp: '00:53', quote: 'Halo, selamat pagi.' } },
    ],
  },
}

test('summarizeCollection membaca hasil akhir dan indikator gagal', () => {
  const s = summarizeCollection(OK_JSON)
  assert.equal(s.hasilAkhir, 'TIDAK COMPLIANT')
  assert.equal(s.isCompliant, false)
  assert.equal(s.totalTerpenuhi, 6)
  assert.equal(s.totalDinilai, 7)
  assert.deepEqual(s.failedIndicators, [2])
  assert.equal(s.deskcollName, 'Ibu Tiwi')
  assert.equal(s.error, null)
})

test('summarizeCollection menandai hasil COMPLIANT', () => {
  const s = summarizeCollection({ evaluation: { hasil_akhir: 'COMPLIANT', checklist_result: [] } })
  assert.equal(s.isCompliant, true)
  assert.deepEqual(s.failedIndicators, [])
})

test('summarizeCollection meneruskan pesan error dari model', () => {
  const s = summarizeCollection({ evaluation: { error: 'kb must contain exactly 7 items, got 5' } })
  assert.equal(s.error, 'kb must contain exactly 7 items, got 5')
  assert.equal(s.hasilAkhir, null)
})

test('summarizeCollection tidak melempar untuk bentuk yang tidak dikenal', () => {
  for (const bad of [null, undefined, {}, { evaluation: null }, { evaluation: [] }, 'teks']) {
    const s = summarizeCollection(bad)
    assert.ok(s.error)
    assert.deepEqual(s.failedIndicators, [])
  }
})

test('checklistItems mengurutkan menurut nomor indikator', () => {
  const items = checklistItems(OK_JSON)
  assert.deepEqual(items.map((i) => i.no), [1, 2])
  assert.equal(items[0].isPass, true)
  assert.equal(items[1].isPass, false)
  assert.equal(items[1].quote, 'saya dengan Ibu Tiwi')
  assert.equal(items[0].timestamp, '00:53')
})

test('checklistItems mengembalikan array kosong untuk input cacat', () => {
  assert.deepEqual(checklistItems(null), [])
  assert.deepEqual(checklistItems({ evaluation: {} }), [])
})

test('checklistItems menoleransi evidence yang hilang', () => {
  const items = checklistItems({
    evaluation: { checklist_result: [{ no: 5, status: 'YA', indikator: 'X' }] },
  })
  assert.equal(items[0].quote, null)
  assert.equal(items[0].timestamp, null)
})

test('speakerCards mengambil emosi dominan', () => {
  const cards = speakerCards(OK_JSON)
  assert.equal(cards.length, 2)
  assert.equal(cards[0].speaker, 'AGENT_BM')
  assert.equal(cards[0].dominantEmotion, 'NETRAL')
  assert.equal(cards[1].dominantEmotion, null)
})

test('speakerCards mengembalikan array kosong bila speaker_stats tidak ada', () => {
  assert.deepEqual(speakerCards({}), [])
  assert.deepEqual(speakerCards(null), [])
})

test('formatSeconds memformat durasi', () => {
  assert.equal(formatSeconds(92.2), '1m 32s')
  assert.equal(formatSeconds(20.4), '0m 20s')
  assert.equal(formatSeconds(null), '—')
})
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system/dashboard
node --test src/views/collection/collectionSummary.test.mjs
```
Expected: FAIL — `Cannot find module .../collectionSummary.js`

- [ ] **Step 3: Tulis implementasi**

Buat `dashboard/src/views/collection/collectionSummary.js`:

```js
// Turunan tampilan dari result_json QC Collection.
//
// Dipisah dari komponen Vue supaya bisa diuji dengan `node --test` tanpa DOM —
// pola yang sama dipakai views/qc/assignTicketData.js.
//
// Kontraknya sama dengan sisi server (compliance/collection_summary.py): bentuk
// JSON yang tidak dikenal TIDAK melempar exception, melainkan mengisi `error`.
// Tiket yang gagal dievaluasi justru yang paling perlu terlihat oleh QC.

const EMPTY_SUMMARY = {
  hasilAkhir: null,
  isCompliant: false,
  totalTerpenuhi: null,
  totalDinilai: null,
  failedIndicators: [],
  deskcollName: null,
  cardholderName: null,
  ringkasan: null,
  error: null,
}

function evaluationOf(resultJson) {
  if (!resultJson || typeof resultJson !== 'object') return null
  const ev = resultJson.evaluation
  if (!ev || typeof ev !== 'object' || Array.isArray(ev)) return null
  return ev
}

function toInt(value) {
  const n = Number(value)
  return Number.isFinite(n) ? Math.trunc(n) : null
}

export function summarizeCollection(resultJson) {
  const ev = evaluationOf(resultJson)
  if (!ev) return { ...EMPTY_SUMMARY, error: 'Hasil evaluasi tidak tersedia.' }
  if (ev.error) return { ...EMPTY_SUMMARY, error: String(ev.error) }

  const items = Array.isArray(ev.checklist_result) ? ev.checklist_result : null
  if (!items) {
    return { ...EMPTY_SUMMARY, error: 'Hasil checklist tidak ditemukan pada evaluasi.' }
  }

  const failedIndicators = items
    .filter((it) => it && String(it.status || '').trim().toUpperCase() === 'TIDAK')
    .map((it) => toInt(it.no))
    .filter((n) => n !== null)
    .sort((a, b) => a - b)

  const hasilAkhir = ev.hasil_akhir ?? null
  return {
    hasilAkhir,
    isCompliant: String(hasilAkhir || '').trim().toUpperCase() === 'COMPLIANT',
    totalTerpenuhi: toInt(ev.total_terpenuhi),
    totalDinilai: toInt(ev.total_dinilai),
    failedIndicators,
    deskcollName: ev.deskcoll_name ?? null,
    cardholderName: ev.cardholder_name ?? null,
    ringkasan: ev.ringkasan ?? null,
    error: null,
  }
}

export function checklistItems(resultJson) {
  const ev = evaluationOf(resultJson)
  if (!ev || !Array.isArray(ev.checklist_result)) return []
  return ev.checklist_result
    .filter((it) => it && typeof it === 'object')
    .map((it) => {
      const evidence = it.evidence && typeof it.evidence === 'object' ? it.evidence : {}
      const status = String(it.status || '').trim().toUpperCase()
      return {
        no: toInt(it.no),
        kbCode: it.kb_code ?? null,
        indikator: it.indikator ?? null,
        pasal: it.pasal ?? null,
        status: status || null,
        isPass: status === 'YA',
        catatan: it.catatan ?? null,
        quote: evidence.quote ?? null,
        timestamp: evidence.timestamp ?? null,
      }
    })
    .sort((a, b) => (a.no ?? 999) - (b.no ?? 999))
}

export function speakerCards(resultJson) {
  if (!resultJson || typeof resultJson !== 'object') return []
  const stats = resultJson.speaker_stats
  if (!Array.isArray(stats)) return []
  return stats
    .filter((s) => s && typeof s === 'object')
    .map((s) => {
      const emotions = s.emotions && typeof s.emotions === 'object' ? s.emotions : {}
      const ranked = Object.entries(emotions).sort((a, b) => b[1] - a[1])
      return {
        speaker: s.speaker ?? '—',
        gender: s.gender ?? null,
        dominantEmotion: ranked.length ? ranked[0][0] : null,
        seconds: Number.isFinite(Number(s.seconds)) ? Number(s.seconds) : 0,
        pct: Number.isFinite(Number(s.pct)) ? Number(s.pct) : 0,
      }
    })
}

export function formatSeconds(seconds) {
  const n = Number(seconds)
  if (!Number.isFinite(n)) return '—'
  const total = Math.round(n)
  return `${Math.floor(total / 60)}m ${total % 60}s`
}
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system/dashboard
node --test src/views/collection/collectionSummary.test.mjs
```
Expected: PASS — `# pass 10`, `# fail 0`

- [ ] **Step 5: Pastikan test frontend lama tetap lulus**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system/dashboard
node --test src/views/qc/assignTicketData.test.mjs
```
Expected: `# pass 14`, `# fail 0`

- [ ] **Step 6: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add dashboard/src/views/collection/collectionSummary.js dashboard/src/views/collection/collectionSummary.test.mjs
git commit -m "feat(dashboard): helper ringkasan hasil QC Collection"
```

---

### Task 7: Komponen laporan checklist

**Files:**
- Create: `dashboard/src/components/CollectionEvaluationView.vue`

**Interfaces:**
- Consumes: `summarizeCollection`, `checklistItems`, `speakerCards`, `formatSeconds` dari `../views/collection/collectionSummary.js` (Task 6)
- Produces: komponen dengan satu prop — `result` (Object, isi `result_json` dari `GET /collection/result/{id}`). Tidak meng-emit event apa pun.

- [ ] **Step 1: Tulis komponen**

Buat `dashboard/src/components/CollectionEvaluationView.vue`:

```vue
<template>
  <div class="coll-eval">
    <!-- Evaluasi tidak terbaca: tampilkan pesannya, jangan render sebagian.
         Tiket seperti ini justru yang paling perlu terlihat oleh QC. -->
    <div v-if="summary.error" class="coll-banner">
      <span class="coll-banner-icon">⚠️</span>
      <div>
        <div class="coll-banner-title">Hasil tidak dapat dibaca</div>
        <p class="coll-banner-msg">{{ summary.error }}</p>
      </div>
    </div>

    <template v-else>
      <!-- Ringkasan -->
      <div class="coll-summary">
        <div :class="['coll-card', 'coll-card-result', summary.isCompliant ? 'is-pass' : 'is-fail']">
          <p class="coll-label">Hasil akhir</p>
          <p class="coll-value">{{ summary.hasilAkhir || '—' }}</p>
          <span class="coll-pill">{{ terpenuhiText }}</span>
        </div>
        <div class="coll-card">
          <p class="coll-label">Total terpenuhi</p>
          <p class="coll-value">{{ terpenuhiText }}</p>
          <p class="coll-sub">Indikator berstatus YA</p>
        </div>
        <div class="coll-card">
          <p class="coll-label">Indikator gagal</p>
          <p class="coll-value">{{ failedText }}</p>
          <p class="coll-sub">{{ summary.failedIndicators.length ? 'Berstatus TIDAK' : 'Tidak ada' }}</p>
        </div>
        <div class="coll-card">
          <p class="coll-label">Durasi panggilan</p>
          <p class="coll-value">{{ result?.audio_duration || '—' }}</p>
          <p class="coll-sub">{{ speakers.length }} speaker</p>
        </div>
      </div>

      <!-- Peringatan bila jumlah indikator bukan 7 (guard skema prompt) -->
      <div v-if="jumlahTidakWajar" class="coll-warn">
        Jumlah indikator yang dinilai bukan 7 ({{ summary.totalDinilai ?? items.length }}).
        Hasil ditampilkan apa adanya — periksa knowledge base campaign.
      </div>

      <!-- Identitas panggilan -->
      <h3 class="coll-section">Identitas panggilan</h3>
      <div class="coll-identity">
        <div class="coll-id-card">
          <div class="coll-id-head">
            <div class="coll-avatar">{{ initials(summary.deskcollName) }}</div>
            <div>
              <p class="coll-id-name">{{ summary.deskcollName || 'Nama tidak disebut' }}</p>
              <p class="coll-id-role">Deskcoll (petugas penagihan)</p>
            </div>
          </div>
          <table class="coll-id-table">
            <tr v-for="row in deskcollRows" :key="row.k">
              <td class="k">{{ row.k }}</td>
              <td :class="['v', { missing: row.missing }]">{{ row.v }}</td>
            </tr>
          </table>
        </div>

        <div class="coll-id-card">
          <div class="coll-id-head">
            <div class="coll-avatar coll-avatar-alt">{{ initials(summary.cardholderName) }}</div>
            <div>
              <p class="coll-id-name">{{ summary.cardholderName || 'Nama tidak disebut' }}</p>
              <p class="coll-id-role">Cardholder / penerima telepon</p>
            </div>
          </div>
          <table class="coll-id-table">
            <tr v-for="row in cardholderRows" :key="row.k">
              <td class="k">{{ row.k }}</td>
              <td :class="['v', { missing: row.missing }]">{{ row.v }}</td>
            </tr>
          </table>
        </div>
      </div>

      <!-- Checklist -->
      <h3 class="coll-section">
        Hasil checklist · {{ items.length }} indikator POJK 22/2023
      </h3>
      <div class="coll-checklist">
        <div v-if="!items.length" class="coll-empty">Tidak ada item checklist.</div>
        <div v-for="item in items" :key="item.kbCode || item.no" :class="['coll-item', { fail: !item.isPass }]">
          <div class="coll-item-head">
            <div>
              <p class="coll-item-pasal">{{ item.no ?? '—' }} · {{ item.pasal || 'Pasal tidak dicatat' }}</p>
              <p class="coll-item-req">{{ item.indikator || '—' }}</p>
            </div>
            <span :class="['coll-status', item.isPass ? 'ya' : 'tidak']">
              {{ item.status || '—' }}
            </span>
          </div>
          <p v-if="item.catatan" class="coll-item-note">{{ item.catatan }}</p>
          <p class="coll-item-quote">
            <template v-if="item.quote">"{{ item.quote }}"<template v-if="item.timestamp"> · {{ item.timestamp }}</template></template>
            <template v-else>Tidak ada kutipan (lihat catatan)</template>
          </p>
        </div>
      </div>

      <!-- Ringkasan naratif -->
      <template v-if="summary.ringkasan">
        <h3 class="coll-section">Ringkasan</h3>
        <p class="coll-ringkasan">{{ summary.ringkasan }}</p>
      </template>

      <p class="coll-footer">
        <b>Catatan:</b> hasil ini dihasilkan otomatis oleh AI dari transkrip panggilan
        dan <b>bukan</b> keputusan resmi kepatuhan. Wajib direview manusia sebelum
        dipakai sebagai dasar tindakan. Field yang ditandai "tidak disebut" memang
        tidak ada dasarnya pada transkrip — tidak diasumsikan.
      </p>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  summarizeCollection,
  checklistItems,
  speakerCards,
  formatSeconds,
} from '../views/collection/collectionSummary.js'

const props = defineProps({ result: { type: Object, default: null } })

const summary = computed(() => summarizeCollection(props.result))
const items = computed(() => checklistItems(props.result))
const speakers = computed(() => speakerCards(props.result))

const terpenuhiText = computed(() => {
  const { totalTerpenuhi, totalDinilai } = summary.value
  if (totalTerpenuhi === null || totalDinilai === null) return '—'
  return `${totalTerpenuhi} / ${totalDinilai}`
})

const failedText = computed(() => {
  const failed = summary.value.failedIndicators
  return failed.length ? `No. ${failed.join(', ')}` : 'Tidak ada'
})

// Prompt mengunci checklist pada 7 item; selain itu tampilkan peringatan.
const jumlahTidakWajar = computed(() => {
  if (summary.value.error) return false
  const dinilai = summary.value.totalDinilai ?? items.value.length
  return dinilai !== 7 || items.value.length !== 7
})

// speaker_stats tidak memberi tahu mana deskcoll dan mana cardholder; yang
// terpanjang bicaranya dipakai sebagai deskcoll — konsisten dengan pola panggilan
// penagihan, dan tetap ditampilkan apa adanya lewat label speaker.
const deskcollSpeaker = computed(() => speakers.value[0] || null)
const cardholderSpeaker = computed(() => speakers.value[1] || null)

function speakerRows(sp) {
  return [
    { k: 'Label speaker', v: sp?.speaker || 'Tidak tersedia', missing: !sp },
    { k: 'Jenis kelamin', v: sp?.gender || 'Tidak tersedia', missing: !sp?.gender },
    {
      k: 'Durasi bicara',
      v: sp ? `${formatSeconds(sp.seconds)} (${sp.pct}%)` : 'Tidak tersedia',
      missing: !sp,
    },
    { k: 'Profil emosi', v: sp?.dominantEmotion || 'Tidak tersedia', missing: !sp?.dominantEmotion },
  ]
}

const deskcollRows = computed(() => speakerRows(deskcollSpeaker.value))
const cardholderRows = computed(() => speakerRows(cardholderSpeaker.value))

function initials(name) {
  if (!name) return '—'
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('')
}
</script>

<style scoped>
.coll-eval { padding: 4px 0 8px; }

.coll-banner {
  display: flex; gap: 12px; align-items: flex-start;
  background: #fef3c7; border: 1px solid #fcd34d; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 8px;
}
.coll-banner-icon { flex: none; }
.coll-banner-title { font-size: 13px; font-weight: 700; color: #92400e; margin: 0 0 3px; }
.coll-banner-msg { font-size: 12.5px; color: #92400e; margin: 0; line-height: 1.55; word-break: break-word; }

.coll-warn {
  background: #fef3c7; border: 1px solid #fcd34d; border-radius: 8px;
  padding: 10px 14px; font-size: 12.5px; color: #92400e; margin-bottom: 18px;
}

.coll-summary {
  display: grid; grid-template-columns: 1.3fr repeat(3, 1fr);
  gap: 12px; margin-bottom: 22px;
}
.coll-card { background: #fff; border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
.coll-card-result { color: #fff; border: none; display: flex; flex-direction: column; justify-content: center; }
.coll-card-result.is-pass { background: #15803d; }
.coll-card-result.is-fail { background: #1e2761; }
.coll-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin: 0 0 6px; font-weight: 700; }
.coll-card-result .coll-label { color: rgba(255, 255, 255, 0.75); }
.coll-value { font-size: 22px; font-weight: 700; margin: 0; }
.coll-sub { font-size: 12px; color: var(--text-muted); margin: 6px 0 0; }
.coll-pill { display: inline-block; margin-top: 8px; align-self: flex-start; font-size: 12px; font-weight: 600; padding: 3px 11px; border-radius: 999px; background: rgba(255, 255, 255, 0.16); }

.coll-section { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); font-weight: 700; margin: 0 0 10px; }

.coll-identity { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 24px; }
.coll-id-card { background: #fff; border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
.coll-id-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.coll-avatar { width: 36px; height: 36px; border-radius: 50%; background: #dbeafe; color: #1e2761; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 12px; flex: none; }
.coll-avatar-alt { background: #f1f5f9; color: #475569; }
.coll-id-name { font-size: 14px; font-weight: 700; margin: 0; }
.coll-id-role { font-size: 11.5px; color: var(--text-muted); margin: 2px 0 0; }
.coll-id-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.coll-id-table td { padding: 5px 0; border-top: 1px solid var(--border); }
.coll-id-table tr:first-child td { border-top: none; }
.coll-id-table td.k { color: var(--text-muted); }
.coll-id-table td.v { text-align: right; font-weight: 600; }
.coll-id-table td.v.missing { color: var(--text-muted); font-weight: 500; font-style: italic; }

.coll-checklist { display: flex; flex-direction: column; gap: 9px; margin-bottom: 22px; }
.coll-item { background: #fff; border: 1px solid var(--border); border-radius: 12px; padding: 13px 16px; }
.coll-item.fail { border-color: #fca5a5; }
.coll-item-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; }
.coll-item-pasal { font-size: 11.5px; color: var(--text-muted); margin: 0 0 3px; }
.coll-item-req { font-size: 13.5px; font-weight: 600; margin: 0; line-height: 1.45; }
.coll-status { flex: none; font-size: 11.5px; font-weight: 700; padding: 3px 11px; border-radius: 999px; }
.coll-status.ya { background: var(--green-bg); color: #16a34a; }
.coll-status.tidak { background: #fee2e2; color: #b91c1c; }
.coll-item-note { font-size: 12.5px; color: var(--text-muted); margin: 8px 0 0; line-height: 1.55; }
.coll-item-quote { font-size: 12px; color: #94a3b8; margin: 5px 0 0; font-style: italic; }

.coll-ringkasan { font-size: 13px; line-height: 1.6; margin: 0 0 22px; }
.coll-footer { font-size: 11.5px; color: var(--text-muted); line-height: 1.6; border-top: 1px solid var(--border); padding-top: 14px; margin: 0; }

.coll-empty { text-align: center; padding: 28px; color: var(--text-muted); font-size: 13px; }

@media (max-width: 860px) {
  .coll-summary { grid-template-columns: 1fr 1fr; }
  .coll-summary .coll-card-result { grid-column: 1 / -1; }
}
@media print {
  .coll-card-result { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .coll-item { break-inside: avoid; }
}
</style>
```

- [ ] **Step 2: Verifikasi komponen ter-build**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system/dashboard
npx vite build 2>&1 | tail -12
```
Expected: build selesai tanpa error (komponen belum dipakai route mana pun, tapi kesalahan sintaks SFC akan tetap muncul saat parsing).

Kalau `npx vite build` gagal karena `node_modules` belum ada, jalankan `npm install` lebih dulu.

- [ ] **Step 3: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add dashboard/src/components/CollectionEvaluationView.vue
git commit -m "feat(dashboard): komponen laporan checklist QC Collection"
```

---

### Task 8: Halaman Results Collection

**Files:**
- Create: `dashboard/src/views/collection/CollectionResultsView.vue`
- Modify: `dashboard/src/router/index.js:84-85` (tambah route), `:129-131` (guard)
- Modify: `dashboard/src/components/SidebarMenu.vue` (grup menu baru + satu computed)

**Interfaces:**
- Consumes: `GET /collection/list_results`, `GET /collection/result/{id}` (Task 5); `CollectionEvaluationView.vue` (Task 7)
- Produces: route `/dashboard/collection/results`

- [ ] **Step 1: Tulis view**

Buat `dashboard/src/views/collection/CollectionResultsView.vue`:

```vue
<template>
  <SidebarLayout title="Results Collection">
    <div class="filter-bar">
      <input
        v-model="searchTicketId"
        class="text-input"
        placeholder="Cari ticket id..."
        @input="debouncedApply"
      />
      <select v-model="filterHasil" class="select-input" @change="applyFilter">
        <option value="">Semua Hasil</option>
        <option value="COMPLIANT">Compliant</option>
        <option value="TIDAK_COMPLIANT">Tidak Compliant</option>
      </select>
      <select v-model="filterStatus" class="select-input" @change="applyFilter">
        <option value="">Semua Status</option>
        <option value="done">Done</option>
        <option value="processing">Processing</option>
        <option value="pending">Pending</option>
        <option value="failed">Failed</option>
      </select>
      <input v-model="dateStart" type="date" class="text-input date-input" title="Tanggal mulai" @change="applyFilter" />
      <input v-model="dateEnd" type="date" class="text-input date-input" title="Tanggal akhir" @change="applyFilter" />
      <button class="btn-clear" @click="clearFilter">Reset</button>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="loading" class="skeleton-list">
      <div class="skeleton-row" v-for="i in 5" :key="i"></div>
    </div>

    <div v-else class="table-card">
      <table class="data-table">
        <thead>
          <tr>
            <th>Ticket ID</th>
            <th>Deskcoll</th>
            <th>Cardholder</th>
            <th>Status</th>
            <th>Hasil</th>
            <th class="num">Terpenuhi</th>
            <th>Indikator Gagal</th>
            <th>Tanggal</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length">
            <td colspan="8" class="empty">Tidak ada tiket collection.</td>
          </tr>
          <template v-for="it in items" :key="it.result_id">
            <tr
              class="data-row"
              :class="{ expanded: expandedId === it.result_id }"
              tabindex="0"
              role="button"
              :aria-expanded="expandedId === it.result_id"
              @click="toggle(it)"
              @keyup.enter="toggle(it)"
            >
              <td class="cell-strong">{{ it.id || '—' }}</td>
              <td>{{ it.deskcoll_name || '—' }}</td>
              <td>{{ it.cardholder_name || '—' }}</td>
              <td>
                <span :class="['status-badge', statusClass(it.status)]">{{ it.status }}</span>
              </td>
              <td>
                <span v-if="it.hasil_akhir" :class="['status-badge', isCompliant(it) ? 'badge-green' : 'badge-red']">
                  {{ it.hasil_akhir }}
                </span>
                <span v-else-if="it.error" class="status-badge badge-amber" :title="it.error">Tidak terbaca</span>
                <span v-else>—</span>
              </td>
              <td class="num">
                {{ it.total_terpenuhi !== null && it.total_dinilai !== null ? `${it.total_terpenuhi} / ${it.total_dinilai}` : '—' }}
              </td>
              <td>{{ it.failed_indicators?.length ? `No. ${it.failed_indicators.join(', ')}` : '—' }}</td>
              <td class="cell-date">{{ formatDate(it.generated_at || it.uploaded_at) }}</td>
            </tr>
            <tr v-if="expandedId === it.result_id" class="expand-row">
              <td colspan="8">
                <div class="expand-content">
                  <div v-if="detailLoading[it.result_id]" class="result-loading">
                    <span class="spinner"></span> Memuat hasil...
                  </div>
                  <CollectionEvaluationView
                    v-else-if="details[it.result_id]?.result"
                    :result="details[it.result_id].result"
                  />
                  <div v-else-if="details[it.result_id]?.error" class="result-failed">
                    ✗ Gagal: {{ details[it.result_id].error }}
                  </div>
                  <div v-else class="result-pending">
                    Status: <strong>{{ it.status }}</strong> — hasil belum tersedia.
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <div class="pagination">
        <span class="total-info">Total: {{ total }} tiket</span>
        <div class="page-controls">
          <button :disabled="page === 1" class="page-btn" @click="goPage(page - 1)">‹</button>
          <span class="page-info">Hal {{ page }} / {{ totalPages }}</span>
          <button :disabled="page >= totalPages" class="page-btn" @click="goPage(page + 1)">›</button>
        </div>
      </div>
    </div>
  </SidebarLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import SidebarLayout from '../../components/SidebarLayout.vue'
import CollectionEvaluationView from '../../components/CollectionEvaluationView.vue'
import apiClient from '../../api/client.js'

const items = ref([])
const total = ref(0)
const page = ref(1)
const limit = 20
const loading = ref(true)
const error = ref('')

const searchTicketId = ref('')
const filterHasil = ref('')
const filterStatus = ref('')
const dateStart = ref('')
const dateEnd = ref('')

const expandedId = ref(null)
const details = ref({})
const detailLoading = ref({})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit)))

function isCompliant(it) {
  return String(it.hasil_akhir || '').trim().toUpperCase() === 'COMPLIANT'
}

function statusClass(status) {
  if (status === 'done') return 'badge-green'
  if (status === 'failed') return 'badge-red'
  return 'badge-gray'
}

function formatDate(iso) {
  if (!iso) return '—'
  const s = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z'
  return new Date(s).toLocaleString('id-ID', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Jakarta',
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params = { page: page.value, limit }
    if (searchTicketId.value.trim()) params.ticket_id = searchTicketId.value.trim()
    if (filterHasil.value) params.hasil = filterHasil.value
    if (filterStatus.value) params.status = filterStatus.value
    if (dateStart.value) params.date_start = dateStart.value
    if (dateEnd.value) params.date_end = dateEnd.value
    const res = await apiClient.get('/collection/list_results', { params })
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Gagal memuat daftar collection.'
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

let timer = null
function debouncedApply() {
  clearTimeout(timer)
  timer = setTimeout(applyFilter, 350)
}

function applyFilter() {
  page.value = 1
  expandedId.value = null
  load()
}

function clearFilter() {
  searchTicketId.value = ''
  filterHasil.value = ''
  filterStatus.value = ''
  dateStart.value = ''
  dateEnd.value = ''
  applyFilter()
}

function goPage(p) {
  page.value = p
  expandedId.value = null
  load()
}

async function toggle(it) {
  if (expandedId.value === it.result_id) {
    expandedId.value = null
    return
  }
  expandedId.value = it.result_id
  if (details.value[it.result_id]) return
  detailLoading.value = { ...detailLoading.value, [it.result_id]: true }
  try {
    const res = await apiClient.get(`/collection/result/${it.result_id}`)
    details.value = { ...details.value, [it.result_id]: res.data }
  } catch (e) {
    details.value = {
      ...details.value,
      [it.result_id]: { error: e?.response?.data?.detail || 'Gagal memuat hasil.' },
    }
  } finally {
    detailLoading.value = { ...detailLoading.value, [it.result_id]: false }
  }
}

onMounted(load)
</script>

<style scoped>
.filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.text-input, .select-input {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px;
  font-size: 13px; background: #fff; color: var(--text);
}
.date-input { min-width: 150px; }
.btn-clear {
  padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px;
  background: #fff; font-size: 13px; cursor: pointer; color: var(--text-muted);
}
.btn-clear:hover { background: #f8fafc; }

.error-box { background: #fee2e2; border: 1px solid #fca5a5; color: #b91c1c; padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 12px; }

.table-card { background: #fff; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th {
  background: #f8fafc; padding: 10px 14px; font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted);
  border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap;
}
.data-table th.num, .data-table td.num { text-align: right; }
.data-row td { padding: 11px 14px; border-bottom: 1px solid #f1f5f9; font-size: 13px; }
.data-row { cursor: pointer; }
.data-row:hover td { background: #f8fafc; }
.data-row.expanded td { background: #eef2ff; }
.cell-strong { font-weight: 700; }
.cell-date { white-space: nowrap; color: var(--text-muted); font-size: 12px; }
.status-badge { font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
.badge-green { background: var(--green-bg); color: #16a34a; }
.badge-red { background: #fee2e2; color: #b91c1c; }
.badge-amber { background: #fef3c7; color: #92400e; }
.badge-gray { background: #f1f5f9; color: var(--text-muted); }
.empty { text-align: center; padding: 40px; color: var(--text-muted); }

.expand-row td { background: #f8fafc; border-bottom: 1px solid var(--border); }
.expand-content { padding: 16px 14px; }
.result-loading, .result-pending, .result-failed { font-size: 13px; color: var(--text-muted); padding: 12px 0; }
.result-failed { color: #b91c1c; }
.spinner {
  display: inline-block; width: 12px; height: 12px; border: 2px solid #cbd5e1;
  border-top-color: #64748b; border-radius: 50%; animation: spin 0.7s linear infinite;
  vertical-align: -1px; margin-right: 6px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.pagination { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-top: 1px solid var(--border); }
.total-info, .page-info { font-size: 12px; color: var(--text-muted); }
.page-controls { display: flex; align-items: center; gap: 8px; }
.page-btn { width: 28px; height: 28px; border: 1px solid var(--border); border-radius: 6px; background: #fff; cursor: pointer; }
.page-btn:disabled { opacity: 0.4; cursor: default; }

.skeleton-list { display: flex; flex-direction: column; gap: 8px; }
.skeleton-row {
  height: 52px; background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%);
  background-size: 200%; border-radius: 8px; animation: shimmer 1.2s infinite;
}
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
</style>
```

- [ ] **Step 2: Daftarkan route**

Di `dashboard/src/router/index.js`, tambahkan entri berikut ke array `routes`, tepat setelah blok `/qc/assign`:

```js
  {
    path: '/dashboard/collection/results',
    component: () => import('../views/collection/CollectionResultsView.vue'),
  },
```

Prefiks `/dashboard` wajib — guard `user?.role === 'qc' && !to.path.startsWith('/dashboard')` di berkas yang sama akan memulangkan role QC dari path lain.

- [ ] **Step 3: Tambahkan guard role**

Di `router.beforeEach` pada berkas yang sama, sisipkan aturan ini setelah guard Transkrip (`if (to.path.startsWith('/dashboard/transcripts') ...)`):

```js
  // QC Collection: sama dengan akses Transkrip — QC / TL QC / QC Support / SPQ Head / Admin.
  if (
    to.path.startsWith('/dashboard/collection') &&
    !['qc', 'spq_head', 'admin', 'team_leader_qc', 'qc_support'].includes(user?.role)
  ) {
    return '/'
  }
```

- [ ] **Step 4: Tambahkan grup menu di sidebar**

Di `dashboard/src/components/SidebarMenu.vue`, tambahkan grup baru tepat setelah `</div>` penutup grup "Dashboard" dan sebelum grup "Upload Data":

```vue
      <div v-if="canCollection" class="menu-group">
        <div class="group-label">QC Collection</div>
        <RouterLink to="/dashboard/collection/results" class="menu-item" active-class="active" :title="collapsed ? 'Results Collection' : ''">
          <span class="icon">🧾</span> <span class="label">Results Collection</span>
        </RouterLink>
      </div>
```

Dan di blok `<script setup>`, tambahkan computed ini setelah `isQcOrSpqHead`:

```js
// Menu QC Collection: sama dengan akses Transkrip.
const canCollection = computed(() => ['qc', 'spq_head', 'admin', 'team_leader_qc', 'qc_support'].includes(auth.user?.role))
```

- [ ] **Step 5: Build frontend**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system/dashboard
npx vite build 2>&1 | tail -12
```
Expected: build selesai tanpa error

- [ ] **Step 6: Verifikasi manual di browser**

1. Pastikan `COLLECTION_CAMPAIGNS=collection_v2` masih terset dan api sudah di-restart (Task 3 Step 9).
2. Buka dashboard, login sebagai SPQ Head / Admin.
3. Menu **QC Collection → Results Collection** harus muncul di sidebar.
4. Buka halamannya — tiket collection dari Task 3 harus tampil dengan kolom Hasil dan Terpenuhi terisi.
5. Klik barisnya — laporan checklist 7 indikator harus terbuka.
6. Buka menu **Results** (sales) — tiket collection **tidak boleh** muncul di sana.
7. Login sebagai role `qc` dan pastikan menu QC Collection tetap dapat diakses (tidak dipulangkan ke `/dashboard/stats`).

- [ ] **Step 7: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add dashboard/src/views/collection/CollectionResultsView.vue dashboard/src/router/index.js dashboard/src/components/SidebarMenu.vue
git commit -m "feat(dashboard): halaman Results Collection + route dan menu"
```

---

### Task 9: Halaman Transkrip Collection

**Files:**
- Create: `dashboard/src/views/collection/CollectionTranscriptsView.vue`
- Modify: `dashboard/src/router/index.js` (satu route tambahan)
- Modify: `dashboard/src/components/SidebarMenu.vue` (satu entri menu tambahan)

**Interfaces:**
- Consumes: `GET /collection/list_transcripts` (Task 5); `PdfViewer.vue` existing (props `resultId`, `filename`); guard route + computed `canCollection` (Task 8)
- Produces: route `/dashboard/collection/transcripts`

- [ ] **Step 1: Tulis view**

Buat `dashboard/src/views/collection/CollectionTranscriptsView.vue`:

```vue
<template>
  <SidebarLayout title="Transkrip Collection">
    <div class="filter-bar">
      <input
        v-model="searchTicketId"
        class="text-input"
        placeholder="Cari ticket id..."
        @input="debouncedApply"
      />
      <select v-model="filterStatus" class="select-input" @change="applyFilter">
        <option value="">Semua Status</option>
        <option value="done">Done</option>
        <option value="processing">Processing</option>
        <option value="pending">Pending</option>
        <option value="failed">Failed</option>
      </select>
      <button class="btn-clear" @click="clearFilter">Reset</button>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="loading" class="skeleton-list">
      <div class="skeleton-row" v-for="i in 5" :key="i"></div>
    </div>

    <div v-else class="table-card">
      <table class="data-table">
        <thead>
          <tr>
            <th>Ticket ID</th>
            <th>File Transkrip</th>
            <th>Campaign</th>
            <th>Status</th>
            <th>Diupload</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length">
            <td colspan="5" class="empty">Tidak ada transkrip collection.</td>
          </tr>
          <template v-for="it in items" :key="it.result_id + '|' + it.filename">
            <tr
              class="data-row"
              :class="{ expanded: expandedKey === rowKey(it) }"
              tabindex="0"
              role="button"
              :aria-expanded="expandedKey === rowKey(it)"
              @click="toggle(it)"
              @keyup.enter="toggle(it)"
            >
              <td class="cell-strong">{{ it.ticket_id || '—' }}</td>
              <td class="cell-file">{{ it.filename }}</td>
              <td>{{ it.campaign || '—' }}</td>
              <td>
                <span :class="['status-badge', statusClass(it.status)]">{{ it.status }}</span>
              </td>
              <td class="cell-date">{{ formatDate(it.uploaded_at) }}</td>
            </tr>
            <tr v-if="expandedKey === rowKey(it)" class="expand-row">
              <td colspan="5">
                <div class="expand-content">
                  <PdfViewer :result-id="it.result_id" :filename="it.filename" />
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <div class="pagination">
        <span class="total-info">Total: {{ total }} transkrip</span>
        <div class="page-controls">
          <button :disabled="page === 1" class="page-btn" @click="goPage(page - 1)">‹</button>
          <span class="page-info">Hal {{ page }} / {{ totalPages }}</span>
          <button :disabled="page >= totalPages" class="page-btn" @click="goPage(page + 1)">›</button>
        </div>
      </div>
    </div>
  </SidebarLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import SidebarLayout from '../../components/SidebarLayout.vue'
import PdfViewer from '../../components/PdfViewer.vue'
import apiClient from '../../api/client.js'

const items = ref([])
const total = ref(0)
const page = ref(1)
const limit = 20
const loading = ref(true)
const error = ref('')

const searchTicketId = ref('')
const filterStatus = ref('')
const expandedKey = ref(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit)))

// Satu result bisa memuat beberapa PDF, jadi kuncinya gabungan result_id + filename.
function rowKey(it) {
  return `${it.result_id}|${it.filename}`
}

function statusClass(status) {
  if (status === 'done') return 'badge-green'
  if (status === 'failed') return 'badge-red'
  return 'badge-gray'
}

function formatDate(iso) {
  if (!iso) return '—'
  const s = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z'
  return new Date(s).toLocaleString('id-ID', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Jakarta',
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params = { page: page.value, limit }
    if (searchTicketId.value.trim()) params.ticket_id = searchTicketId.value.trim()
    if (filterStatus.value) params.status = filterStatus.value
    const res = await apiClient.get('/collection/list_transcripts', { params })
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Gagal memuat daftar transkrip collection.'
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

let timer = null
function debouncedApply() {
  clearTimeout(timer)
  timer = setTimeout(applyFilter, 350)
}

function applyFilter() {
  page.value = 1
  expandedKey.value = null
  load()
}

function clearFilter() {
  searchTicketId.value = ''
  filterStatus.value = ''
  applyFilter()
}

function goPage(p) {
  page.value = p
  expandedKey.value = null
  load()
}

function toggle(it) {
  expandedKey.value = expandedKey.value === rowKey(it) ? null : rowKey(it)
}

onMounted(load)
</script>

<style scoped>
.filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.text-input, .select-input {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px;
  font-size: 13px; background: #fff; color: var(--text);
}
.btn-clear {
  padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px;
  background: #fff; font-size: 13px; cursor: pointer; color: var(--text-muted);
}
.btn-clear:hover { background: #f8fafc; }

.error-box { background: #fee2e2; border: 1px solid #fca5a5; color: #b91c1c; padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 12px; }

.table-card { background: #fff; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th {
  background: #f8fafc; padding: 10px 14px; font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted);
  border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap;
}
.data-row td { padding: 11px 14px; border-bottom: 1px solid #f1f5f9; font-size: 13px; }
.data-row { cursor: pointer; }
.data-row:hover td { background: #f8fafc; }
.data-row.expanded td { background: #eef2ff; }
.cell-strong { font-weight: 700; }
.cell-file { word-break: break-all; }
.cell-date { white-space: nowrap; color: var(--text-muted); font-size: 12px; }
.status-badge { font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 999px; }
.badge-green { background: var(--green-bg); color: #16a34a; }
.badge-red { background: #fee2e2; color: #b91c1c; }
.badge-gray { background: #f1f5f9; color: var(--text-muted); }
.empty { text-align: center; padding: 40px; color: var(--text-muted); }

.expand-row td { background: #f8fafc; border-bottom: 1px solid var(--border); }
.expand-content { padding: 14px; }

.pagination { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-top: 1px solid var(--border); }
.total-info, .page-info { font-size: 12px; color: var(--text-muted); }
.page-controls { display: flex; align-items: center; gap: 8px; }
.page-btn { width: 28px; height: 28px; border: 1px solid var(--border); border-radius: 6px; background: #fff; cursor: pointer; }
.page-btn:disabled { opacity: 0.4; cursor: default; }

.skeleton-list { display: flex; flex-direction: column; gap: 8px; }
.skeleton-row {
  height: 52px; background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%);
  background-size: 200%; border-radius: 8px; animation: shimmer 1.2s infinite;
}
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
</style>
```

- [ ] **Step 2: Daftarkan route**

Di `dashboard/src/router/index.js`, tambahkan tepat setelah route `/dashboard/collection/results`:

```js
  {
    path: '/dashboard/collection/transcripts',
    component: () => import('../views/collection/CollectionTranscriptsView.vue'),
  },
```

Guard `to.path.startsWith('/dashboard/collection')` dari Task 8 sudah mencakup route ini — tidak perlu aturan baru.

- [ ] **Step 3: Tambahkan entri menu**

Di `dashboard/src/components/SidebarMenu.vue`, di dalam grup "QC Collection" yang dibuat pada Task 8, tambahkan satu `RouterLink` setelah entri Results Collection:

```vue
        <RouterLink to="/dashboard/collection/transcripts" class="menu-item" active-class="active" :title="collapsed ? 'Transkrip Collection' : ''">
          <span class="icon">🎧</span> <span class="label">Transkrip Collection</span>
        </RouterLink>
```

- [ ] **Step 4: Build frontend**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system/dashboard
npx vite build 2>&1 | tail -12
```
Expected: build selesai tanpa error

- [ ] **Step 5: Verifikasi manual di browser**

1. Buka **QC Collection → Transkrip Collection** — PDF transkrip milik campaign collection harus terdaftar.
2. Klik satu baris — PdfViewer harus membuka PDF-nya.
3. Buka menu **Transkrip** (Recording Tickets) — transkrip collection tidak boleh muncul di sana.

- [ ] **Step 6: Jalankan seluruh uji sebagai penutup**

Run:
```bash
cd /data/scorecard_v2/telemarketing-qc-system
docker compose run --rm --no-deps -T api sh -c "pip install -q pytest && python -m pytest tests/ -q"
cd dashboard && node --test src/views/collection/collectionSummary.test.mjs && node --test src/views/qc/assignTicketData.test.mjs
```
Expected: `52 passed, 6 failed` di backend (6 kegagalan pre-existing yang sama seperti baseline) dan `# fail 0` pada kedua berkas uji frontend

- [ ] **Step 7: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
git add dashboard/src/views/collection/CollectionTranscriptsView.vue dashboard/src/router/index.js dashboard/src/components/SidebarMenu.vue
git commit -m "feat(dashboard): halaman Transkrip Collection + route dan menu"
```

---

## Catatan penyimpangan dari spec

- Spec menyebut `tests/test_collection_router.py` untuk menguji pengecualian tiket collection dari daftar sales. Uji itu dipindah ke `tests/test_campaign_filters.py` (Task 4), yang memeriksa ekspresi SQL yang terbentuk. Alasannya: repo ini tidak punya harness `TestClient` + database uji, dan seluruh test yang ada memakai objek palsu. Kebenaran endpoint diverifikasi manual di Task 5 Step 10.
- Spec tidak menyebut `compliance/collection_summary.py`. Modul ini ditambahkan supaya logika penurunan ringkasan bisa diuji murni, terpisah dari router — sejalan dengan pemisahan `collectionSummary.js` di sisi frontend yang memang ada di spec.
- Spec menyebut berkas frontend `views/collection/collectionSummary.js`; test-nya diletakkan bersebelahan sebagai `collectionSummary.test.mjs`, mengikuti pola `views/qc/assignTicketData.test.mjs`.
