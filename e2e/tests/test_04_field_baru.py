"""Field respons yang datang bersama port A2/A4/A6/A9 — sisi yang dibaca dashboard."""
import allure
import requests


@allure.epic("Telemarketing QC")
@allure.feature("Field respons baru")
class TestFieldBaru:

    @allure.story("recording_types terisi dari validasi rekaman worker")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description("""Ditulis worker dari `compliance.recording_validation` (merge
    4-service 21 September 2026): tepat satu `recording_utama`; sisanya
    `recording_perbaikan` atau label alasan rekaman itu tidak dinilai.""")
    def test_recording_types(self, tiket, api, auth):
        it = self._baris(api, auth, tiket[0])
        rt = it.get("recording_types")
        allure.attach(str(rt), "recording_types", allure.attachment_type.TEXT)
        assert rt, "recording_types kosong — worker tidak menuliskannya"
        assert sum(1 for r in rt if r["tag"] == "recording_utama") == 1

    @allure.story("Kolom baru ada di payload, dengan bawaan yang benar")
    def test_field_tersedia(self, tiket, api, auth):
        it = self._baris(api, auth, tiket[0])
        for k in ("document_mismatches", "manual_approved_at", "manual_approved_by",
                  "qc_checked_at", "qc_checked_by", "reprocess_active"):
            assert k in it, f"field {k} tidak ada di respons"
        assert it["document_mismatches"] == [], "tanpa dokumen, mismatch harus daftar kosong"

    @allure.story("reprocess_active milik repo prod tidak hilang saat port")
    @allure.description("Penjaga regresi: field ini TIDAK ada di repo dev; kalau port "
                        "mengambil skema dev apa adanya, ia lenyap dan tombol Reprocess "
                        "kembali enable padahal server menolak dengan 409.")
    def test_reprocess_active_bertahan(self, tiket, api, auth):
        it = self._baris(api, auth, tiket[0])
        assert it["reprocess_active"] is False

    @staticmethod
    def _baris(api, auth, rid):
        r = requests.get(f"{api}/list_results", headers=auth,
                         params={"page": 1, "limit": 50}, timeout=60)
        r.raise_for_status()
        for it in r.json()["items"]:
            if it["result_id"] == rid:
                return it
        raise AssertionError(f"result {rid} tidak muncul di /list_results")
