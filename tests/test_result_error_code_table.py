"""Regresi: helper tabel Error Code milik endpoint detail result.

Commit b8f8432 (refaktor audio/STT) menghapus ``_with_error_code_table`` beserta
dua helper pendukungnya dari ``api/routers/transcript.py`` tanpa menghapus
pemanggilnya di ``get_result``. Akibatnya setiap ``GET /result/{id}`` untuk row
berstatus ``done`` melempar ``NameError`` -> HTTP 500, dan dashboard menampilkan
"Gagal memuat data" pada baris yang sudah selesai diproses.
"""

from api.routers import transcript


def test_membangun_error_code_table_dari_error_codes_llm():
    result_json = {
        "evaluation": {
            "error_codes": [
                {"error_code": "B10", "trigger_source": {"reason": "SC_CL_01 tidak dibacakan"}}
            ]
        }
    }

    out = transcript._with_error_code_table(result_json)

    table = out["evaluation"]["error_code_table"]
    assert [row["error_code"] for row in table] == ["B10"]


def test_setiap_baris_ditandai_appealable_tanpa_banding():
    result_json = {
        "evaluation": {
            "error_codes": [
                {"error_code": "B10", "trigger_source": {"reason": "SC_CL_01 tidak dibacakan"}}
            ]
        }
    }

    row = transcript._with_error_code_table(result_json)["evaluation"]["error_code_table"][0]

    assert row["appealable"] is True
    assert row["appeal"] is None


def test_result_json_tanpa_evaluation_dikembalikan_apa_adanya():
    assert transcript._with_error_code_table({"transcript": "x"}) == {"transcript": "x"}
