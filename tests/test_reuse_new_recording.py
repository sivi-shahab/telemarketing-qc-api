"""Upload ``reuse`` hanya meng-clone hasil yang sudah menilai SEMUA file upload.

16 Oktober 2026: sebelumnya cukup ticket id-nya sama, sehingga recording baru untuk
ID yang sama (JOB-3 mengupload ulang grup berisi PDF tambahan) ikut di-clone dari
evaluasi recording pertama dan tidak pernah dinilai.
"""
import uuid
from datetime import datetime, timedelta

from db import crud
from db.models import Result

T0 = datetime(2026, 10, 15, 4, 0)


def _seed(db, files, hours=0, status="done"):
    r = Result(id=uuid.uuid4(), campaign="Cashline", status=status,
               source_files=files, uploaded_at=T0 + timedelta(hours=hours))
    db.add(r)
    db.flush()
    return r


def _tid():
    return f"ZR{uuid.uuid4().hex[:8]}"


def test_file_sama_tetap_di_clone(db):
    t = _tid()
    a = _seed(db, [f"{t}_1.pdf"])
    assert crud.pick_reusable_done_result(db, t, [f"{t}_1.pdf"]).id == a.id


def test_recording_baru_tidak_di_clone(db):
    t = _tid()
    _seed(db, [f"{t}_1.pdf"])
    assert crud.pick_reusable_done_result(db, t, [f"{t}_1.pdf", f"{t}_2.pdf"]) is None
    assert crud.pick_reusable_done_result(db, t, [f"{t}_2.pdf"]) is None


def test_ambil_hasil_yang_mencakup_semua_file(db):
    t = _tid()
    _seed(db, [f"{t}_1.pdf"], hours=0)
    both = _seed(db, [f"{t}_1.pdf", f"{t}_2.pdf"], hours=1)
    _seed(db, [f"{t}_1.pdf"], hours=2)  # lebih baru tapi tidak memuat file ke-2
    pick = crud.pick_reusable_done_result(db, t, [f"{t}_2.pdf", f"{t}_1.pdf"])
    assert pick.id == both.id


def test_tanpa_source_files_perilaku_lama(db):
    t = _tid()
    _seed(db, [f"{t}_1.pdf"], hours=0)
    newest = _seed(db, [f"{t}_9.pdf"], hours=1)
    assert crud.pick_reusable_done_result(db, t).id == newest.id
