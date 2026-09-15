"""Dashboard: bundle hasil build benar-benar memuat sisi konsumen field baru."""
import os

import allure

DIST = os.getenv("E2E_DIST", "/dist")


def _bundle(nama_chunk):
    aset = os.path.join(DIST, "assets")
    isi = ""
    for f in os.listdir(aset):
        if f.startswith(nama_chunk) and f.endswith((".js", ".css")):
            with open(os.path.join(aset, f), encoding="utf-8", errors="ignore") as fh:
                isi += fh.read()
    return isi


@allure.epic("Telemarketing QC")
@allure.feature("Dashboard (bundle produksi)")
class TestDashboard:

    @allure.story("Bobot scorecard v4 ter-bake ke bundle")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("""Bobot ditulis MATI di `EvaluationView.vue`, jadi satu-satunya
    bukti yang meyakinkan adalah tidak adanya lagi angka v3 di artefak yang dikirim ke
    browser — memeriksa sumbernya saja tidak membuktikan apa yang sampai ke pengguna.""")
    def test_bobot_v4(self):
        js = _bundle("EvaluationView")
        assert js, "chunk EvaluationView tidak ditemukan di dist/assets"
        for lama in ("108.75", "41.25"):
            assert lama not in js, f"bobot v3 {lama} masih ada di bundle"
        for baru in ("35.5", "13.25"):
            assert baru in js, f"bobot v4 {baru} tidak ada di bundle"

    @allure.story("Field baru dirender ResultsView")
    def test_field_baru_dirender(self):
        js = _bundle("ResultsView")
        for k in ("stage-progress", "document_mismatches", "recording_types", "poi-note"):
            assert k in js, f"{k} tidak ada di bundle ResultsView"

    @allure.story("Kelas status tahap ada di CSS, bukan hanya di JS")
    @allure.description("""`:class=\"'stage-' + st.state\"` dirakit dinamis, jadi namanya
    tidak pernah muncul utuh di JS. Kalau CSS-nya tertinggal, tabel progres tetap tampil
    tetapi tanpa warna dan ikon — gagal yang tidak menimbulkan error apa pun.""")
    def test_kelas_tahap_di_css(self):
        css = _bundle("ResultsView")
        for k in ("stage-selesai", "stage-berjalan", "stage-menunggu"):
            assert k in css, f"kelas {k} tidak ada di CSS"

    @allure.story("Istilah Statistics diselaraskan ke versi dev")
    def test_istilah_stats(self):
        js = _bundle("StatsView")
        for baru in ("Data Leads", "Total Sales Call Activity", "Error Rate"):
            assert baru in js, f"istilah '{baru}' tidak ada"
        for lama in ("Avg Failure Rate", "Total Recording"):
            assert lama not in js, f"istilah lama '{lama}' masih ada"

    @allure.story("Slot dokumen pengecualian MUS menerima JPG/PNG")
    def test_slot_mus(self):
        js = _bundle("ResultsView")
        assert "mus_exception_confirmation" in js
        assert "image/jpeg" in js and "image/png" in js

    @allure.story("Favicon memakai %BASE_URL%, bukan path mati yang 404")
    @allure.description("Prod sempat menulis /telemarketing_qc_system/bank-mega-mark.png "
                        "padahal aplikasinya dilayani di root — berkasnya tidak pernah ada "
                        "di sana.")
    def test_favicon(self):
        with open(os.path.join(DIST, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        assert "/telemarketing_qc_system/bank-mega-mark.png" not in html
        assert "bank-mega-mark.png" in html
        assert os.path.exists(os.path.join(DIST, "bank-mega-mark.png"))
