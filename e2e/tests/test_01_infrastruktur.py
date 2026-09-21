"""Lapisan dasar: skema, migrasi, dan kolom yang dituntut kode yang baru di-port."""
import allure
import requests


@allure.epic("Telemarketing QC")
@allure.feature("Infrastruktur & migrasi")
class TestInfrastruktur:

    @allure.story("API hidup")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_health(self, api):
        r = requests.get(f"{api}/health", timeout=30)
        assert r.status_code == 200, r.text

    @allure.story("Migrasi alembic sampai kepala terbaru")
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.description("""Migrasi dijalankan dari NOL di skema `dashboard`, sama seperti
    produksi. `0053` adalah migrasi `results.current_stage` (Batch 9); `0054`-`0057`
    datang dari merge 4-service 21 September 2026 (A 0056-0059, dinomori ulang). Kalau
    rantainya bercabang (dua migrasi mengaku nomor yang sama), langkah ini gagal.""")
    def test_alembic_di_kepala_0057(self, q):
        [(v,)] = q("select version_num from alembic_version")
        allure.attach(v, "alembic_version", allure.attachment_type.TEXT)
        assert v == "0057"

    @allure.story("Kolom current_stage ada dan bentuknya benar")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_kolom_current_stage(self, q):
        rows = q("""select data_type, character_maximum_length, is_nullable
                    from information_schema.columns
                    where table_schema='dashboard' and table_name='results'
                      and column_name='current_stage'""")
        assert rows, "kolom current_stage tidak ada — migrasi 0053 tidak jalan"
        tipe, panjang, nullable = rows[0]
        assert (tipe, panjang, nullable) == ("character varying", 50, "YES")

    @allure.story("Seluruh tabel aplikasi mendarat di skema dashboard")
    def test_tabel_di_skema_dashboard(self, q):
        [(n,)] = q("select count(*) from information_schema.tables where table_schema='dashboard'")
        allure.attach(str(n), "jumlah tabel", allure.attachment_type.TEXT)
        assert n >= 20, f"hanya {n} tabel — migrasi tidak lengkap"

    @allure.story("LLM yang dipakai adalah STUB, bukan endpoint produksi")
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.description("""Penjaga keselamatan: kalau LLM_BASE_URL kelak salah menunjuk
    endpoint sungguhan, e2e akan membakar biaya dan mengirim data ke luar. Test ini yang
    menangkapnya lebih dulu.""")
    def test_llm_distub(self, api):
        r = requests.get("http://e2e-stub-llm:9099/health", timeout=30)
        assert r.status_code == 200 and r.json().get("ok") is True
