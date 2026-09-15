"""Bentuk prompt yang BENAR-BENAR dikirim worker ke model (Batch 8)."""
import allure
import requests

STUB = "http://e2e-stub-llm:9099"


@allure.epic("Telemarketing QC")
@allure.feature("Bentuk prompt & caching")
class TestBentukPrompt:

    @allure.story("Urutan blok: KB -> SCORECARD -> REFERENCE DATA -> TRANSCRIPT")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("""Penataan Batch 8 mendorong bagian yang identik antar-tiket ke
    DEPAN supaya ter-cache. Unit test hanya membuktikan fungsi penyusunnya; test ini
    membuktikan bentuk itu benar-benar sampai ke permintaan HTTP — stub mencatat urutan
    header blok pada user message yang ia terima.""")
    def test_urutan_blok(self, tiket):
        jejak = requests.get(f"{STUB}/_jejak", timeout=30).json()["panggilan"]
        nilai = [p for p in jejak if p["jenis"] == "penilaian"]
        assert nilai, "tidak ada panggilan penilaian yang tercatat di stub"
        urutan = nilai[0]["urutan_blok"]
        allure.attach(" -> ".join(urutan), "urutan blok", allure.attachment_type.TEXT)
        assert urutan[0] == "KB", f"TRANSCRIPT masih di depan: {urutan}"
        assert urutan.index("SCORECARD") < urutan.index("TRANSCRIPT")
        assert urutan[-1] == "TRANSCRIPT"

    @allure.story("REFERENCE DATA berdiri sebagai blok sendiri")
    @allure.description("Dulu ia digabung ke ekor SCORECARD oleh pemanggil, yang membuat "
                        "lapisan scorecard ikut berubah tiap tiket dan batal ter-cache.")
    def test_reference_blok_sendiri(self, tiket):
        jejak = requests.get(f"{STUB}/_jejak", timeout=30).json()["panggilan"]
        urutan = [p for p in jejak if p["jenis"] == "penilaian"][0]["urutan_blok"]
        assert "REFERENCE DATA" in urutan
        assert urutan.index("SCORECARD") < urutan.index("REFERENCE DATA") < urutan.index("TRANSCRIPT")

    @allure.story("Klasifikasi jenis rekaman dipanggil sekali untuk satu tiket")
    @allure.description("Satu panggilan untuk SELURUH rekaman, bukan satu per rekaman — "
                        "label 'perbaikan' hanya berarti bila model melihat rekaman yang "
                        "diperbaikinya.")
    def test_klasifikasi_sekali(self, tiket):
        jejak = requests.get(f"{STUB}/_jejak", timeout=30).json()["panggilan"]
        klas = [p for p in jejak if p["jenis"] == "klasifikasi"]
        allure.attach(str(len(klas)), "jumlah panggilan klasifikasi", allure.attachment_type.TEXT)
        assert len(klas) == 1, f"klasifikasi dipanggil {len(klas)}x, seharusnya 1x"
