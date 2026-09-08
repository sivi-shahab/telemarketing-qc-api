"""Pindahkan akun login dari DB monolit (``bankqc``) ke DB App B (``da.dashboard``).

Monolit ``telemarketing-qc-system`` membawa 29 user beserta batas campaign-nya,
sementara App B hasil pemisahan baru berisi akun admin. Skrip ini memindahkan
sisanya sekali jalan, dan boleh dijalankan berulang: yang sudah ada dilewati.

APA YANG DIPINDAH DAN APA YANG TIDAK

- ``users`` dan ``user_campaigns``: ikut.
- ``roles``: TIDAK. Sepuluh key-nya identik di kedua sisi, tapi isi target lebih
  baru (``team_leader_qc`` 25 permission di App B vs 23 di monolit, buah dari
  "Upload Database Sales untuk Team Leader QC"). Menyalinnya = memundurkan RBAC.
- ``campaigns``: TIDAK. Isinya prompt/scorecard/KB, bukan urusan akun. Batas
  campaign per user aman tanpa itu karena ``user_campaigns.campaign`` menyimpan
  NAMA campaign, bukan id — tidak ada pemetaan id yang bisa meleset.
- Akun admin monolit: TIDAK. Admin App B sudah ada dan sedang dipakai.

ID SUMBER SENGAJA DIBUANG. Monolit memakai id 3..35 sedangkan App B sudah
memakai 2 dan 3, jadi membawa id lama berarti tabrakan primary key sekarang dan
sequence yang meleset nanti. Target yang menerbitkan id; ``user_campaigns``
menyusul lewat username, dan ``created_by`` — yang di monolit menunjuk admin
monolit — diarahkan ke admin App B (lihat ``--created-by``).

PASSWORD TIDAK DI-RESET. Kedua sisi memakai bcrypt ``$2b$12$`` dan kolom yang
sama persis, jadi hash-nya disalin apa adanya dan orang tetap login dengan
password lamanya.

CARA MENJALANKAN

DB monolit sudah mati dan data dir-nya (``data/postgres``) adalah satu-satunya
salinan yang tersisa. JANGAN menjalankan Postgres langsung di atas direktori itu
— begitu dinyalakan, WAL-nya diputar dan isinya berubah. Salin dulu:

    sudo cp -a /data/scorecard_v2/telemarketing-qc-system/data/postgres /tmp/pgsrc
    docker run -d --name qc-src-pg -v /tmp/pgsrc:/var/lib/postgresql/data \\
        -e POSTGRES_PASSWORD=probe --network qc-net postgres:16-alpine

Lalu, dari dalam container API (punya modul aplikasi + kredensial target):

    docker exec -it telemarketing-qc-api-api-1 python scripts/migrate_users_from_monolith.py \\
        --source-dsn postgresql://bankqc@qc-src-pg:5432/bankqc              # dry-run
    docker exec -it telemarketing-qc-api-api-1 python scripts/migrate_users_from_monolith.py \\
        --source-dsn postgresql://bankqc@qc-src-pg:5432/bankqc --commit     # tulis

Tanpa ``--commit`` tidak ada satu pun baris yang ditulis; yang keluar hanya
rencananya. Bereskan container sumbernya (``docker rm -f qc-src-pg``) dan
salinannya setelah selesai.
"""
import argparse
import sys
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Akun admin App B yang dijadikan "pembuat" user-user pindahan. Bisa ditimpa
# lewat --created-by kalau kelak bukan akun ini yang memegang.
DEFAULT_CREATED_BY = "22050660"


@dataclass
class Skipped:
    username: str
    reason: str


@dataclass
class Plan:
    """Rencana yang bisa dibaca manusia sebelum satu baris pun ditulis."""
    inserts: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    created_by_id: Optional[int] = None
    warnings: list = field(default_factory=list)

    @property
    def total_scopes(self) -> int:
        return sum(len(u["campaigns"]) for u in self.inserts)


def _norm(value) -> str:
    return str(value or "").strip().casefold()


def build_plan(
    source_users: Iterable[dict],
    source_scopes: Iterable[dict],
    target_users: Iterable[dict],
    target_role_keys: Iterable[str],
    created_by_username: str = DEFAULT_CREATED_BY,
) -> Plan:
    """Susun daftar user yang boleh masuk beserta alasan yang lain ditolak.

    Murni: tidak menyentuh database, jadi keputusannya bisa diuji utuh (lihat
    ``tests/test_migrate_users_from_monolith.py``) dan hasil dry-run-nya persis
    sama dengan yang akan dijalankan ``--commit``.
    """
    target_users = list(target_users)
    roles = {_norm(k) for k in target_role_keys}
    existing_usernames = {_norm(u["username"]) for u in target_users}
    existing_emails = {_norm(u["email"]) for u in target_users}

    plan = Plan()

    for u in target_users:
        if _norm(u["username"]) == _norm(created_by_username):
            plan.created_by_id = u["id"]
            break
    if plan.created_by_id is None:
        plan.warnings.append(
            f"Akun '{created_by_username}' tidak ada di target: created_by diisi NULL."
        )

    # Scope dikelompokkan per id SUMBER dulu; pemetaan ke user target baru bisa
    # dilakukan setelah insert, lewat username.
    scopes_by_source_id: dict = {}
    for s in source_scopes:
        bucket = scopes_by_source_id.setdefault(s["user_id"], [])
        if s["campaign"] not in bucket:  # sumber pernah menyimpan baris kembar
            bucket.append(s["campaign"])

    for row in source_users:
        username = row["username"]
        role = _norm(row["role"])

        if role == "admin":
            plan.skipped.append(Skipped(username, "akun admin — admin App B sudah ada"))
            continue
        if _norm(username) in existing_usernames:
            plan.skipped.append(Skipped(username, "username sudah ada di target"))
            continue
        if _norm(row["email"]) in existing_emails:
            # users.email UNIQUE: tanpa penjagaan ini insert-nya gagal di tengah
            # jalan dan menyisakan migrasi setengah matang.
            plan.skipped.append(Skipped(username, f"email {row['email']} sudah dipakai di target"))
            continue
        if role not in roles:
            # Gagal tertutup: user tanpa role sah akan lolos semua pemeriksaan RBAC
            # yang membandingkan key role, atau justru tidak bisa apa-apa. Dua-duanya
            # keputusan yang tidak boleh diambil diam-diam oleh skrip migrasi.
            plan.skipped.append(Skipped(username, f"role '{row['role']}' tidak dikenal di target"))
            continue

        plan.inserts.append({
            "username": username,
            "name": row.get("name"),
            "email": row["email"],
            "hashed_password": row["hashed_password"],
            "role": row["role"],
            "is_active": row.get("is_active", True),
            "created_at": row.get("created_at"),
            # created_by sumber menunjuk id di DB monolit; satu-satunya terjemahan
            # yang benar di App B adalah admin-nya sendiri.
            "created_by": plan.created_by_id if row.get("created_by") is not None else None,
            "campaigns": list(scopes_by_source_id.get(row["id"], [])),
        })
        # Sumber pernah menyimpan dua baris dengan username beda tapi email sama;
        # daftar ini ikut tumbuh supaya bentrokan sesama pendatang juga ketahuan.
        existing_usernames.add(_norm(username))
        existing_emails.add(_norm(row["email"]))

    return plan


# ---------------------------------------------------------------------------
# Bagian yang menyentuh database
# ---------------------------------------------------------------------------

def fetch_source(dsn: str):
    """Baca ``users`` + ``user_campaigns`` dari Postgres monolit."""
    import psycopg2
    import psycopg2.extras

    with psycopg2.connect(dsn) as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""select id, username, name, email, hashed_password, role,
                              is_active, created_at, created_by
                       from users order by id""")
        users = [dict(r) for r in cur.fetchall()]
        cur.execute("select user_id, campaign from user_campaigns order by id")
        scopes = [dict(r) for r in cur.fetchall()]
    return users, scopes


def fetch_target(session):
    from qc_core.db.models import Role, User

    users = [
        {"id": u.id, "username": u.username, "email": u.email, "role": u.role}
        for u in session.query(User).all()
    ]
    return users, [r.key for r in session.query(Role).all()]


def apply_plan(session, plan: Plan) -> None:
    """Tulis rencana dalam SATU transaksi: gagal di tengah = tidak ada yang masuk."""
    from qc_core.db.models import User, UserCampaign

    for row in plan.inserts:
        campaigns = row["campaigns"]
        user = User(**{k: v for k, v in row.items() if k != "campaigns"})
        session.add(user)
        # flush per user: id-nya terbit sekarang dan langsung dipakai scope-nya,
        # jadi tidak perlu mencari ulang lewat username setelah commit.
        session.flush()
        for campaign in campaigns:
            session.add(UserCampaign(user_id=user.id, campaign=campaign))
    session.commit()


def _print_plan(plan: Plan, commit: bool) -> None:
    print(f"\n{'MENULIS' if commit else 'DRY-RUN'} — {len(plan.inserts)} user, "
          f"{plan.total_scopes} baris scope campaign\n")
    print(f"{'USERNAME':<14} {'ROLE':<16} {'NAMA':<28} CAMPAIGN")
    print("-" * 88)
    for u in plan.inserts:
        print(f"{u['username']:<14} {u['role']:<16} {(u['name'] or ''):<28} "
              f"{', '.join(u['campaigns']) or '(tanpa batas)'}")

    if plan.skipped:
        print(f"\nDilewati ({len(plan.skipped)}):")
        for s in plan.skipped:
            print(f"  - {s.username}: {s.reason}")

    print(f"\ncreated_by -> {plan.created_by_id if plan.created_by_id is not None else 'NULL'}")
    for w in plan.warnings:
        print(f"PERINGATAN: {w}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source-dsn", required=True,
                    help="DSN Postgres monolit, mis. postgresql://bankqc@qc-src-pg:5432/bankqc")
    ap.add_argument("--created-by", default=DEFAULT_CREATED_BY,
                    help=f"username admin App B yang dicatat sebagai pembuat (default: {DEFAULT_CREATED_BY})")
    ap.add_argument("--commit", action="store_true",
                    help="benar-benar menulis; tanpa ini hanya menampilkan rencana")
    args = ap.parse_args(argv)

    from api.dependencies import get_db

    source_users, source_scopes = fetch_source(args.source_dsn)
    session = next(get_db())
    try:
        target_users, target_roles = fetch_target(session)
        plan = build_plan(
            source_users=source_users,
            source_scopes=source_scopes,
            target_users=target_users,
            target_role_keys=target_roles,
            created_by_username=args.created_by,
        )
        print(f"Sumber: {len(source_users)} user, {len(source_scopes)} baris scope. "
              f"Target: {len(target_users)} user, {len(target_roles)} role.")
        _print_plan(plan, args.commit)

        if not args.commit:
            print("\nTidak ada yang ditulis. Ulangi dengan --commit untuk menjalankannya.")
            return 0
        if not plan.inserts:
            print("\nTidak ada yang perlu ditulis.")
            return 0
        apply_plan(session, plan)
        print(f"\nSelesai: {len(plan.inserts)} user masuk.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
