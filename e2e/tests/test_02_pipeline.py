"""Alur utuh: unggah transkrip -> Celery -> worker -> hasil tersimpan."""
import allure
import requests


@allure.epic("Telemarketing QC")
@allure.feature("Pipeline penilaian")
class TestPipeline:

    @allure.story("Tiket selesai diproses ujung ke ujung")
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.description("""Empat PDF transkrip NYATA diunggah lewat `/upload_transcript`,
    dikerjakan worker Celery sungguhan (parsing PDF, klasifikasi jenis rekaman, penilaian
    scorecard), lalu hasilnya dibaca kembali lewat `/result/{id}`. Satu-satunya yang
    distub adalah panggilan modelnya.""")
    def test_tiket_selesai(self, tiket, api, auth):
        rid, _tid = tiket
        r = requests.get(f"{api}/result/{rid}", headers=auth, timeout=30)
        assert r.status_code == 200
        body = r.json()
        allure.attach(str(body)[:2000], "respons /result", allure.attachment_type.TEXT)
        assert body["status"] == "done"
        assert body.get("result"), "status done tetapi payload hasil kosong"

    @allure.story("Baris hasil tersimpan di database")
    def test_baris_database(self, tiket, q):
        rid, _ = tiket
        [(n,)] = q("select count(*) from results where id = %s", rid)
        assert n == 1
        [(m,)] = q("select count(*) from result_data where result_id = %s", rid)
        assert m >= 1, "result_data tidak tertulis"

    @allure.story("Checkpoint current_stage ditulis worker")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("""`_Tahap.catat` menulis checkpoint ke `results.current_stage`
    lewat `crud.set_result_stage` (Batch 9 + W1). Sesudah tiket selesai, nilainya harus
    checkpoint TERAKHIR — `tandai_selesai`.""")
    def test_current_stage_terisi(self, tiket, q):
        rid, _ = tiket
        [(stage,)] = q("select current_stage from results where id = %s", rid)
        allure.attach(str(stage), "current_stage", allure.attachment_type.TEXT)
        assert stage == "tandai_selesai", f"checkpoint terakhir tidak tercatat: {stage}"

    @allure.story("Snapshot reference_data ikut tersimpan di result_json")
    @allure.description("""Fondasi repo prod: `reference_data` mentah disisipkan ke
    result_json supaya hierarki Statistics, scope Team Leader dan timer SLA tidak perlu
    menembak App A tiap dashboard dibuka. Kalau port W1 membuang baris itu, jalur snapshot
    seluruhnya mati — dan tidak ada error yang muncul.""")
    def test_snapshot_reference_data(self, tiket, q):
        rid, _ = tiket
        [(js,)] = q("select result_json from result_data where result_id = %s"
                    " order by created_at desc limit 1", rid)
        assert "reference_data" in js, "kunci reference_data hilang dari result_json"
