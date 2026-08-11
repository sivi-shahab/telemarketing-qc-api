"""reference data tables (tms_cashline + ascend_custp) + one-time CSV seed

Migrates the CASHLINE (TMS) and CARD HOLDER (Ascend) reference exports out of the
local CSVs (``csv_bank/19 Juni 2026/*.csv``) and into PostgreSQL, so the runtime
reference-data builder reads from the DB instead of the filesystem.

Each export column becomes a real column: the DB column name is the original CSV
header verbatim (hyphens / UPPERCASE preserved via identifier quoting), all typed
``Text`` (the export is untyped strings). Lookup keys:
  - ``tms_cashline.result_id``       : matched against the customer/session ID.
  - ``ascend_custp.CUST_LOCAL_NAME`` : matched trimmed + lower-cased.

This is an MVP mockup of the real TMS/Ascend tables; production swaps the DB
connection for the real schema (same column names). The CSV seed is
idempotent-by-emptiness: it only loads when the target table is empty, so
re-running ``alembic upgrade head`` (or pointing at a DB seeded another way)
won't duplicate rows. Schema creation does NOT depend on the CSVs being present
(only the seed step does).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-25 00:00:00.000000
"""
import csv
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# <repo_root>/csv_bank/19 Juni 2026/*.csv  (versions -> migrations -> db -> root)
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_DATA_DIR = os.path.join(_REPO_ROOT, "csv_bank", "19 Juni 2026")
CASHLINE_CSV = os.path.join(_DATA_DIR, "data_tms_19062026.csv")
ASCEND_CSV = os.path.join(_DATA_DIR, "data_ascend_19062026.csv")


def _read_csv(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _seed(conn, table: str, key_col: str, csv_path: str) -> None:
    """Load ``csv_path`` into ``table`` (column name == CSV header) if empty.

    Rows with an empty ``key_col`` are skipped (the key column is NOT NULL).
    """
    rows = _read_csv(csv_path)
    if not rows:
        return
    existing = conn.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
    if existing:
        return
    payload = [r for r in rows if str(r.get(key_col) or "").strip()]
    if not payload:
        return
    headers = list(rows[0].keys())
    tbl = sa.table(table, *[sa.column(h) for h in headers])
    op.bulk_insert(tbl, payload)


def upgrade() -> None:
    op.create_table(
        "tms_cashline",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("result_id", sa.String(100), nullable=False),
        sa.Column("prospect_id", sa.Text),
        sa.Column("customer_id", sa.Text),
        sa.Column("file_id", sa.Text),
        sa.Column("cust_name", sa.Text),
        sa.Column("agent_id", sa.Text),
        sa.Column("submit_time", sa.Text),
        sa.Column("qc_id", sa.Text),
        sa.Column("approve_time", sa.Text),
        sa.Column("turli", sa.Text),
        sa.Column("segmen", sa.Text),
        sa.Column("alamat-pengiriman", sa.Text),
        sa.Column("send-mail-to", sa.Text),
        sa.Column("send-message-to", sa.Text),
        sa.Column("no-npwp-new", sa.Text),
        sa.Column("no-telp-rumah-new", sa.Text),
        sa.Column("no-telp-kantor-new", sa.Text),
        sa.Column("nik-new", sa.Text),
        sa.Column("e-statement-new", sa.Text),
        sa.Column("alamat-email-new", sa.Text),
        sa.Column("kirim-pesan-melalui", sa.Text),
        sa.Column("kantor-rt-new", sa.Text),
        sa.Column("kantor-rw-new", sa.Text),
        sa.Column("kantor-provinsi-new", sa.Text),
        sa.Column("kantor-kabupatenkota-new", sa.Text),
        sa.Column("kantor-kecamatan-new", sa.Text),
        sa.Column("kantor-kelurahan-new", sa.Text),
        sa.Column("kantor-kode-pos-new", sa.Text),
        sa.Column("nama-perusahaan-new", sa.Text),
        sa.Column("alamat-rumah-1-new", sa.Text),
        sa.Column("rumah-rt-new", sa.Text),
        sa.Column("rumah-rw-new", sa.Text),
        sa.Column("rumah-provinsi-new", sa.Text),
        sa.Column("rumah-kabupatenkota-new", sa.Text),
        sa.Column("rumah-kecamatan-new", sa.Text),
        sa.Column("rumah-kelurahan-new", sa.Text),
        sa.Column("rumah-kode-pos-new", sa.Text),
        sa.Column("alamat-kantor-1-new", sa.Text),
        sa.Column("alamat-rumah-2-new", sa.Text),
        sa.Column("alamat-kantor-2-new", sa.Text),
        sa.Column("checlist-jika-ada-perubahan", sa.Text),
        sa.Column("source-code", sa.Text),
        sa.Column("jenis-kartu-yang-dikehendaki", sa.Text),
        sa.Column("max-transfer", sa.Text),
        sa.Column("nominal-transfer", sa.Text),
        sa.Column("tenor", sa.Text),
        sa.Column("cicilan-per-bulan", sa.Text),
        sa.Column("plan-code", sa.Text),
        sa.Column("nama-bank", sa.Text),
        sa.Column("nomor-rekening", sa.Text),
        sa.Column("nama-di-rekening", sa.Text),
        sa.Column("admin-fee", sa.Text),
        sa.Column("biaya-transfer", sa.Text),
        sa.Column("alamat-rumah-chk", sa.Text),
        sa.Column("alamat-kantor-chk", sa.Text),
        sa.Column("alamat-pengiriman-kartu-chk", sa.Text),
        sa.Column("no-npwp-chk", sa.Text),
        sa.Column("no-telp-rumah-chk", sa.Text),
        sa.Column("no-telp-kantor-chk", sa.Text),
        sa.Column("nik-chk", sa.Text),
        sa.Column("e-statement-chk", sa.Text),
        sa.Column("alamat-email-chk", sa.Text),
        sa.Column("send-message", sa.Text),
        sa.Column("pekerjaan", sa.Text),
        sa.Column("bidang-usaha", sa.Text),
        sa.Column("jabatan", sa.Text),
        sa.Column("no-ktpkitas", sa.Text),
        sa.Column("pendaftaran-credit-shield", sa.Text),
        sa.Column("privy", sa.Text),
        sa.Column("tanpa-perubahan-data-ntb-chk", sa.Text),
        sa.Column("grab", sa.Text),
        sa.Column("enroll", sa.Text),
        sa.Column("finance", sa.Text),
        sa.Column("status", sa.Text),
        sa.Column("los", sa.Text),
        sa.Column("cld-amount", sa.Text),
    )
    op.create_index("ix_tms_cashline_result_id", "tms_cashline", ["result_id"])

    op.create_table(
        "ascend_custp",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("CUST_NBR", sa.Text),
        sa.Column("CUST_OPER_CODE", sa.Text),
        sa.Column("CUST_TYPE", sa.Text),
        sa.Column("CUST_LOCAL_NAME", sa.String(255), nullable=False),
        sa.Column("CUST_ADDR1", sa.Text),
        sa.Column("CUST_ADDR2", sa.Text),
        sa.Column("CUST_ADD_CITY", sa.Text),
        sa.Column("CUST_ADD_PROVINCE", sa.Text),
        sa.Column("CUST_ADD_ZIPCODE", sa.Text),
        sa.Column("CUST_PHONE", sa.Text),
        sa.Column("CUST_RES_TYPE", sa.Text),
        sa.Column("CUST_RES_PERIOD", sa.Text),
        sa.Column("CUST_SEX", sa.Text),
        sa.Column("CUST_MARITAL_ST", sa.Text),
        sa.Column("CUST_QUALIFICATION", sa.Text),
        sa.Column("CUST_ID_NBR", sa.Text),
        sa.Column("CUST_DTE_BIRTH", sa.Text),
        sa.Column("CUST_MOM_NAME", sa.Text),
        sa.Column("CUST_WORK_ID", sa.Text),
        sa.Column("CUST_NATIONALITY", sa.Text),
        sa.Column("CUST_SUPP_RLNSHIP", sa.Text),
        sa.Column("CUST_EMP_NAME", sa.Text),
        sa.Column("CUST_EMP_ADDR1", sa.Text),
        sa.Column("CUST_EMP_ADDR2", sa.Text),
        sa.Column("CUST_EMP_ADDR3", sa.Text),
        sa.Column("CUST_EMP_ADDR4", sa.Text),
        sa.Column("CUST_EMP_CITY", sa.Text),
        sa.Column("CUST_EMP_ZIP", sa.Text),
        sa.Column("CUST_OCC_CODE", sa.Text),
        sa.Column("CUST_OCC_PER", sa.Text),
        sa.Column("CUST_EMP_PHONE", sa.Text),
        sa.Column("CUST_ANN_SALARY", sa.Text),
        sa.Column("CUST_OTH_INCOME", sa.Text),
        sa.Column("CUST_GRLNSHIP", sa.Text),
        sa.Column("CUST_GLOCAL_NAME", sa.Text),
        sa.Column("CUST_GENG_NAME", sa.Text),
        sa.Column("CUST_GADDR1", sa.Text),
        sa.Column("CUST_GADDR2", sa.Text),
        sa.Column("CUST_GADDR3", sa.Text),
        sa.Column("CUST_GADDR4", sa.Text),
        sa.Column("CUST_GADD_CITY", sa.Text),
        sa.Column("CUST_GADD_PROVINCE", sa.Text),
        sa.Column("CUST_GADD_ZIPCODE", sa.Text),
        sa.Column("CUST_GPHONE", sa.Text),
        sa.Column("CUST_GSEX", sa.Text),
        sa.Column("CUST_GMARITAL_ST", sa.Text),
        sa.Column("CUST_GQUALIFICATION", sa.Text),
        sa.Column("CUST_GID_NBR", sa.Text),
        sa.Column("CUST_PLC_BIRTH", sa.Text),
        sa.Column("CUST_GDTE_BIRTH", sa.Text),
        sa.Column("CUST_GWORK_ID", sa.Text),
        sa.Column("CUST_GEMP_NAME", sa.Text),
        sa.Column("CUST_GEMP_ADDR1", sa.Text),
        sa.Column("CUST_GEMP_ADDR2", sa.Text),
        sa.Column("CUST_GEMP_ZIP", sa.Text),
        sa.Column("CUST_GOCC_CODE", sa.Text),
        sa.Column("CUST_GOCC_PER", sa.Text),
        sa.Column("CUST_GEMP_PHONE", sa.Text),
        sa.Column("CUST_GANN_SALARY", sa.Text),
        sa.Column("CUST_MADDR1", sa.Text),
        sa.Column("CUST_MADDR2", sa.Text),
        sa.Column("CUST_MADD_CITY", sa.Text),
        sa.Column("CUST_MADD_PROVINCE", sa.Text),
        sa.Column("CUST_MADD_ZIPCODE", sa.Text),
        sa.Column("CUST_CNAME", sa.Text),
        sa.Column("CUST_CORP_EMBOSS_NAME", sa.Text),
        sa.Column("CUST_CPHONE", sa.Text),
        sa.Column("CUST_CREG_DATE", sa.Text),
        sa.Column("CUST_CREG_NBR", sa.Text),
        sa.Column("CUST_CBUSINESS", sa.Text),
        sa.Column("CUST_CBANK", sa.Text),
        sa.Column("CUST_CBANK_ACCT", sa.Text),
        sa.Column("CUST_CCONTACT", sa.Text),
        sa.Column("CUST_COLLECTOR", sa.Text),
        sa.Column("CUST_MEMO", sa.Text),
        sa.Column("CUST_CRLIMIT", sa.Text),
        sa.Column("CUST_AVAIL_CREDIT", sa.Text),
        sa.Column("CUST_CASH_LIMIT", sa.Text),
        sa.Column("CUST_AVAIL_CASH", sa.Text),
        sa.Column("CUST_TEMP_CRLIMIT", sa.Text),
        sa.Column("CUST_PERM_CRLIMIT", sa.Text),
        sa.Column("CUST_DATE_TEMP_CRLIMIT_EFF", sa.Text),
        sa.Column("CUST_DATE_TEMP_CRLIMIT_EXP", sa.Text),
        sa.Column("CUST_CURR_CODE", sa.Text),
        sa.Column("CUST_ADDR3", sa.Text),
        sa.Column("CUST_ADDR4", sa.Text),
        sa.Column("CUST_MADDR3", sa.Text),
        sa.Column("CUST_MADDR4", sa.Text),
        sa.Column("CUST_EMAIL_ADDR", sa.Text),
        sa.Column("CUST_MOBILE_PHONE", sa.Text),
        sa.Column("CUST_ADDR_CODE", sa.Text),
        sa.Column("CUST_FILE_BUFFER", sa.Text),
        sa.Column("CUST_INSTL_LIMIT", sa.Text),
        sa.Column("CUST_AVAIL_INSTL", sa.Text),
        sa.Column("CUST_STDALN_INSTL", sa.Text),
        sa.Column("CUST_AVAIL_STDALN_INS", sa.Text),
        sa.Column("CUST_NODE_ID", sa.Text),
        sa.Column("CUST_FAMILY_SIZE", sa.Text),
        sa.Column("CUST_SPOUSE_NAME", sa.Text),
        sa.Column("CUST_TAX_ID", sa.Text),
        sa.Column("CUST_DIN", sa.Text),
        sa.Column("CUST_TITLE", sa.Text),
        sa.Column("CUST_CR_CARD1", sa.Text),
        sa.Column("CUST_CR_CARD_LMT1", sa.Text),
        sa.Column("CUST_CR_CARD2", sa.Text),
        sa.Column("CUST_CR_CARD_LMT2", sa.Text),
        sa.Column("CUST_CIF", sa.Text),
        sa.Column("CUST_HOME_OWNSHP", sa.Text),
        sa.Column("CUST_DATE_MAINT", sa.Text),
        sa.Column("CUST_USER_MAINT", sa.Text),
        sa.Column("CUST_TIME_MAINT", sa.Text),
        sa.Column("CUST_FILE_DATE", sa.Text),
    )
    op.create_index(
        "ix_ascend_custp_cust_local_name", "ascend_custp", ["CUST_LOCAL_NAME"]
    )

    # One-time seed from the CSVs (skipped if the table is already populated).
    conn = op.get_bind()
    _seed(conn, "tms_cashline", "result_id", CASHLINE_CSV)
    _seed(conn, "ascend_custp", "CUST_LOCAL_NAME", ASCEND_CSV)


def downgrade() -> None:
    op.drop_index("ix_ascend_custp_cust_local_name", table_name="ascend_custp")
    op.drop_table("ascend_custp")
    op.drop_index("ix_tms_cashline_result_id", table_name="tms_cashline")
    op.drop_table("tms_cashline")
