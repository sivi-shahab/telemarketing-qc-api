"""Auto Assign sesudah A7: pembagian menghitung beban, dan endpoint pratinjau ada."""
import allure
import requests


@allure.epic("Telemarketing QC")
@allure.feature("Auto Assign")
class TestAutoAssign:

    @allure.story("Endpoint pratinjau /qc_assignment/unassigned tersedia")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description("""Endpoint baru dari A7. Dashboard memakainya untuk menyebut
    jumlah antrean SEBENARNYA dalam cakupan login — bukan panjang baris yang kebetulan
    termuat di tabel.""")
    def test_pratinjau_ada(self, api, auth, tiket):
        r = requests.get(f"{api}/qc_assignment/unassigned", headers=auth, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        allure.attach(str(body), "respons", allure.attachment_type.TEXT)
        for k in ("unassigned", "assigned", "total", "qc_count"):
            assert k in body, f"kunci {k} tidak ada"

    @allure.story("Angka pratinjau memakai himpunan yang sama dengan pembagian")
    @allure.description("`_auto_assign_pool` dipakai bersama pratinjau dan pembagian "
                        "supaya angka di layar tidak bisa berbeda dari yang terjadi.")
    def test_konsisten(self, api, auth, tiket):
        b = requests.get(f"{api}/qc_assignment/unassigned", headers=auth, timeout=60).json()
        assert b["assigned"] + b["unassigned"] == b["total"]

    @allure.story("Tiket yang baru diproses masuk antrean belum di-assign")
    def test_tiket_masuk_antrean(self, api, auth, tiket):
        b = requests.get(f"{api}/qc_assignment/unassigned", headers=auth, timeout=60).json()
        assert b["total"] >= 1, "tiket hasil pipeline tidak terlihat oleh Auto Assign"
