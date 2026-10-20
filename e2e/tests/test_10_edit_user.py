"""Edit User (20 Oktober 2026): ganti NIP/password/role lewat HTTP terhadap stack e2e.

Tiket di-assign lewat ``POST /qc_assignment`` (jalur yang sama dengan menu Assign
Ticket; tiketnya hasil pipeline fixture ``tiket``). Baris ``qc_assignments`` dengan
kapitalisasi/spasi tak seragam disisipkan langsung lewat fixture ``db`` karena tidak
ada jalur HTTP yang menulisnya begitu.
"""
import os
import uuid

import allure
import requests

DIST = os.getenv("E2E_DIST", "/dist")


def _rand():
    return uuid.uuid4().hex[:8]


def _buat(api, auth, role="qc", password="pw-awal-123"):
    nip = f"e2e_qc_{_rand()}"
    r = requests.post(f"{api}/auth/create_user", headers=auth, timeout=30, json={
        "username": nip, "email": f"{nip}@e2e.local", "password": password,
        "role": role, "name": "E2E User"})
    assert r.status_code == 200, r.text
    return r.json()["id"], nip, password


def _patch(api, auth, uid, **body):
    return requests.patch(f"{api}/auth/users/{uid}", headers=auth, json=body, timeout=30)


def _riwayat(api, auth, uid):
    r = requests.get(f"{api}/auth/users/history", headers=auth, params={"user_id": uid}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _assign(api, auth, tiket_id, nip):
    r = requests.post(f"{api}/qc_assignment", headers=auth, timeout=30,
                      data={"ticket_id": tiket_id, "qc_username": nip})
    assert r.status_code == 200, r.text


def _login(api, u, p):
    return requests.post(f"{api}/auth/login", data={"username": u, "password": p}, timeout=30)


@allure.epic("Telemarketing QC")
@allure.feature("Edit User")
class TestEditUser:

    @allure.story("Ganti NIP memindahkan tiket dan riwayat assign")
    def test_ganti_nip_memindahkan_assignment(self, api, auth, db, q, tiket):
        _rid, tid = tiket
        uid, nip, pw = _buat(api, auth)
        _assign(api, auth, tid, nip)
        baru = nip.upper() + "_baru"
        r = _patch(api, auth, uid, username=baru)
        assert r.status_code == 200, r.text
        assert r.json()["username"] == baru

        ada = requests.get(f"{api}/qc_assignments", headers=auth, params={"ticket_ids": tid}, timeout=30).json()
        assert [a["qc_username"] for a in ada] == [baru]
        assert q("select qc_username from qc_assignments where ticket_id=%s", tid) == [(baru,)]
        # Tidak ada sisa NIP lama di kolom username mana pun yang diuji.
        assert q("select count(*) from qc_assignment_events where lower(qc_username)=%s "
                 "or lower(previous_qc_username)=%s", nip, nip) == [(0,)]
        assert q("select count(*) from qc_assignment_events where ticket_id=%s and qc_username=%s",
                 tid, baru)[0][0] >= 1

        ev = [e for e in _riwayat(api, auth, uid) if e["field"] == "username"]
        assert len(ev) == 1
        assert (ev[0]["old_value"], ev[0]["new_value"]) == (nip, baru)
        assert ev[0]["target_username"] == baru and ev[0]["actor_username"] == "e2e-admin"
        # Login dengan NIP baru jalan, NIP lama tidak.
        assert _login(api, baru, pw).status_code == 200
        assert _login(api, nip, pw).status_code == 401

    @allure.story("Baris assignment berkapitalisasi/berspasi lain ikut pindah")
    def test_nip_beda_kapital_dan_spasi_ikut_pindah(self, api, auth, db, q):
        uid, nip, _ = _buat(api, auth)
        kotor = f"E2E-KOTOR-{_rand()}"
        with db.cursor() as c:
            c.execute('SET search_path TO "dashboard", public')
            c.execute("insert into qc_assignments (ticket_id, qc_username) values (%s, %s)",
                      (kotor, f"  {nip.upper()} "))
            c.execute("insert into qc_assignment_events (ticket_id, action, qc_username, "
                      "previous_qc_username, actor_username, source) values (%s,'reassign',%s,%s,%s,'manual')",
                      (kotor, f" {nip.upper()}", f"{nip} ", nip.upper()))
        baru = f"{nip}_baru"
        assert _patch(api, auth, uid, username=baru).status_code == 200
        assert q("select qc_username from qc_assignments where ticket_id=%s", kotor) == [(baru,)]
        assert q("select qc_username, previous_qc_username, actor_username from qc_assignment_events "
                 "where ticket_id=%s", kotor) == [(baru, baru, baru)]

    @allure.story("Kapitalisasi NIP sendiri bukan 409; NIP user lain tetap 409")
    def test_kapitalisasi_nip_sendiri_bukan_409(self, api, auth):
        uid, nip, _ = _buat(api, auth)
        r = _patch(api, auth, uid, username=nip.upper())
        assert r.status_code == 200, r.text
        assert r.json()["username"] == nip.upper()
        uid2, nip2, _ = _buat(api, auth)
        r = _patch(api, auth, uid2, username=nip.lower())
        assert r.status_code == 409, r.text

    @allure.story("Ganti password: lama 401, baru 200, riwayat tanpa nilai")
    def test_login_dengan_password_baru(self, api, auth):
        uid, nip, lama = _buat(api, auth)
        assert _login(api, nip, lama).status_code == 200
        baru = "pw-baru-456"
        assert _patch(api, auth, uid, password=baru).status_code == 200
        assert _login(api, nip, lama).status_code == 401
        assert _login(api, nip, baru).status_code == 200
        ev = [e for e in _riwayat(api, auth, uid) if e["field"] == "password"]
        assert len(ev) == 1 and ev[0]["old_value"] is None and ev[0]["new_value"] is None
        assert baru not in str(_riwayat(api, auth, uid)) and lama not in str(_riwayat(api, auth, uid))

    @allure.story("QC jadi TL tercatat (role + left_qc_at); kembali jadi QC menghapusnya")
    def test_qc_jadi_tl_tercatat_left_qc_at(self, api, auth, q):
        uid, nip, _ = _buat(api, auth)
        assert q("select left_qc_at from users where id=%s", uid) == [(None,)]
        r = _patch(api, auth, uid, role="team_leader_qc")
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "team_leader_qc"
        ev = [e for e in _riwayat(api, auth, uid) if e["field"] == "role"]
        assert [(e["old_value"], e["new_value"]) for e in ev] == [("qc", "team_leader_qc")]
        assert q("select left_qc_at is not null from users where id=%s", uid) == [(True,)]

        assert _patch(api, auth, uid, role="qc").status_code == 200
        assert q("select left_qc_at from users where id=%s", uid) == [(None,)]
        ev = [(e["old_value"], e["new_value"]) for e in _riwayat(api, auth, uid) if e["field"] == "role"]
        assert ("team_leader_qc", "qc") in ev and len(ev) == 2

    @allure.story("Bundle dashboard memuat UI Edit User")
    def test_bundle_dashboard_memuat_edit_user(self):
        aset = os.path.join(DIST, "assets")
        isi = ""
        for f in os.listdir(aset):
            if f.startswith("ManageUserView") and f.endswith(".js"):
                with open(os.path.join(aset, f), encoding="utf-8", errors="ignore") as fh:
                    isi += fh.read()
        assert isi, "chunk ManageUserView tidak ada di dist/assets"
        for s in ("Riwayat Perubahan", "Tiket dan seluruh riwayat akan ikut pindah ke NIP baru.",
                  "Tiket hari ini yang belum dikerjakan akan dibagi ulang"):
            assert s in isi, f"{s!r} tidak ada di bundle"
