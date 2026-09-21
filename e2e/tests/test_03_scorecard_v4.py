"""Bobot Scorecard v4 — angka yang benar-benar dihitung server, bukan yang ditulis LLM."""
import allure
import requests


@allure.epic("Telemarketing QC")
@allure.feature("Scorecard v4")
class TestScorecardV4:

    @allure.story("Skor maksimal memakai bobot v4")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("""Stub menyatakan nasabah tertarik Mega Cashline DAN Mega Ultima
    Shield, tanpa MUS Kartu Kredit. Bobot v4 revisi 18 September 2026 (SC_CL_43 menambah
    1,25 ke MUS): 100 + 36,75 = **136,75**. Bobot v3 akan memberi 108,75 + 41,25 = 150.""")
    def test_max_score_136_75(self, tiket, api, auth):
        rid, _ = tiket
        item = self._baris(api, auth, rid)
        allure.attach(str(item.get("maximum_score")), "maximum_score", allure.attachment_type.TEXT)
        assert item["maximum_score"] == 136.75, \
            f"bobot bukan v4 (dapat {item['maximum_score']}, v3 akan 150)"

    @allure.story("Batas lulus 90% dari skor maksimal")
    def test_passing_grade(self, tiket, api, auth):
        rid, _ = tiket
        item = self._baris(api, auth, rid)
        assert abs(item["passing_grade"] - 0.9 * 136.75) < 0.01, item["passing_grade"]

    @allure.story("Skor DITURUNKAN server, bukan dibaca dari keluaran LLM")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("""Stub sengaja TIDAK mengirim `maximum_score`, `passing_grade`
    maupun `ai_score` di keluarannya. Kalau angkanya tetap muncul dan benar, berarti
    server menurunkannya sendiri lewat `_max_score`/`_passing_grade` — persis perubahan
    A2. Kalau dibaca apa adanya dari LLM, ketiganya akan kosong.""")
    def test_skor_diturunkan_bukan_dibaca(self, tiket, api, auth):
        rid, _ = tiket
        item = self._baris(api, auth, rid)
        for k in ("maximum_score", "passing_grade", "ai_score"):
            assert item.get(k) is not None, f"{k} kosong — server tidak menurunkannya"

    @allure.story("Satu item BELUM_SESUAI memotong tepat bobotnya")
    @allure.description("SC_CL_24 bobot 10 gagal -> 136,75 - 10 = 126,75.")
    def test_potongan_item(self, tiket, api, auth):
        rid, _ = tiket
        item = self._baris(api, auth, rid)
        allure.attach(str(item.get("ai_score")), "ai_score", allure.attachment_type.TEXT)
        assert item["ai_score"] == 126.75, item["ai_score"]

    @staticmethod
    def _baris(api, auth, rid):
        r = requests.get(f"{api}/list_results", headers=auth,
                         params={"page": 1, "limit": 50}, timeout=60)
        r.raise_for_status()
        for it in r.json()["items"]:
            if it["result_id"] == rid:
                return it
        raise AssertionError(f"result {rid} tidak muncul di /list_results")
