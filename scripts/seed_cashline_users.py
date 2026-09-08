"""Seed login users for every Cashline Area Manager, Team Leader and Sales Agent
from the ACTIVE Sales Database ("Update Sales Telemarketing …").

Implements final_change.md → "Perubahan 16 Juli 2026 fase 1", poin 3:
create all Area Manager / Team Leader / Sales Agent users, filtered to
DEDICATED = "Cashline" (column F).

Source of truth = the active sales-database xlsx (read via ``active_sales_map``):
  - Sales Agent : username = NIP BARU (col C), name = NAME (col D)
  - Team Leader : username = NIP TL   (col H), name = NAMA TL (col I)
  - Area Manager: username = NIP AM   (col J, header "NIP TLM"), name = NAMA AM (col K)

These usernames are exactly what the Statistics/Results scoping matches against
(``cashline_agent_ids_for_agent`` / ``_for_tl`` / ``_for_am``), so the created
logins are correctly scoped out of the box.

Conventions (confirmed with the requester):
  - email    = ``<nip>@bank.local`` (unique per NIP; mirrors the 0001 admin seed)
  - password = one fixed default (``SEED_PASSWORD`` env, default ``Cashline2026!``),
               bcrypt-hashed via ``api.auth.hash_password``.

Idempotent: a user whose username OR email already exists is skipped. Tiers are
processed Area Manager -> Team Leader -> Sales Agent, so a NIP that appears in more
than one tier keeps its highest role.

Run INSIDE the api container (has DB + MinIO + app modules):
    docker exec -it telemarketing-qc-system-api-1 \
        python scripts/seed_cashline_users.py            # dry-run (no writes)
    docker exec -it telemarketing-qc-system-api-1 \
        python scripts/seed_cashline_users.py --commit   # actually create users
Optional: SEED_PASSWORD=... to override the default password.
"""
import os
import sys

from api.auth import hash_password
from api.dependencies import get_db
from qc_core.sales_lookup import active_sales_map, _norm
from qc_core.db.models import User

DEFAULT_PASSWORD = os.environ.get("SEED_PASSWORD", "Cashline2026!")
EMAIL_DOMAIN = "bank.local"
CASHLINE = "cashline"


def _collect_tiers(cash_entries):
    """Return an ordered list of (nip, name, role), de-duplicated by NIP with role
    precedence Area Manager > Team Leader > Sales Agent."""
    tiers = []
    seen = set()

    def add(nip, name, role):
        nip = _norm(nip)
        if not nip or nip in seen:
            return
        seen.add(nip)
        tiers.append((nip, _norm(name) or nip, role))

    for e in cash_entries:  # Area Managers first (col J NIP / col K name)
        add(e.get("nip_am"), e.get("area_manager"), "area_manager")
    for e in cash_entries:  # then Team Leaders (col H NIP / col I name)
        add(e.get("nip_tl"), e.get("team_leader"), "team_leader")
    for e in cash_entries:  # then Sales Agents (col C NIP / col D name)
        add(e.get("nip_baru"), e.get("name"), "sales_agent")
    return tiers


def main(commit: bool) -> None:
    db = next(get_db())
    sales_map = active_sales_map(db)
    if not sales_map:
        print("ERROR: no active sales database / could not parse it.", file=sys.stderr)
        sys.exit(1)

    cash = [e for e in sales_map.values() if _norm(e.get("dedicated")).casefold() == CASHLINE]
    tiers = _collect_tiers(cash)
    hashed = hash_password(DEFAULT_PASSWORD)

    created = {"area_manager": 0, "team_leader": 0, "sales_agent": 0}
    skipped = []
    to_create = []
    for nip, name, role in tiers:
        email = f"{nip}@{EMAIL_DOMAIN}"
        existing = (
            db.query(User)
            .filter((User.username == nip) | (User.email == email))
            .first()
        )
        if existing is not None:
            skipped.append((nip, role, existing.role))
            continue
        to_create.append((nip, name, email, role))
        created[role] += 1
        if commit:
            db.add(User(
                username=nip,
                name=name,
                email=email,
                hashed_password=hashed,
                role=role,
                is_active=True,
            ))

    if commit:
        db.commit()

    mode = "COMMIT" if commit else "DRY-RUN"
    print(f"[{mode}] Cashline sales-map rows: {len(cash)} | candidate users: {len(tiers)}")
    print(f"[{mode}] would create -> area_manager={created['area_manager']} "
          f"team_leader={created['team_leader']} sales_agent={created['sales_agent']} "
          f"(total {sum(created.values())})")
    print(f"[{mode}] skipped (username/email already exists): {len(skipped)}")
    for nip, want_role, have_role in skipped[:20]:
        print(f"    - {nip}: wanted {want_role}, already exists as {have_role}")
    if len(skipped) > 20:
        print(f"    ... (+{len(skipped) - 20} more)")
    print(f"[{mode}] email = <nip>@{EMAIL_DOMAIN} | password = "
          f"{'(env SEED_PASSWORD)' if 'SEED_PASSWORD' in os.environ else DEFAULT_PASSWORD!r}")
    if not commit:
        print("[DRY-RUN] no rows written. Re-run with --commit to create the users.")


if __name__ == "__main__":
    main("--commit" in sys.argv)
