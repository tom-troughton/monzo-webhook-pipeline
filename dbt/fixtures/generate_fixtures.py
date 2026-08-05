"""Generates synthetic raw/ transaction fixtures for local dbt development.

Mirrors the shape functions/shared/blob_writer.py actually persists:
raw/YYYY/MM/DD/{transaction_id}.json containing {"source", "transaction"}.
All data here is fictional - no real Monzo account was involved.

Re-run after editing the DATA below to regenerate fixtures/raw/:
    python generate_fixtures.py
"""
import json
from pathlib import Path

FIXTURES_ROOT = Path(__file__).parent / "raw"

ACCOUNTS = {
    "personal": "acc_00009xJ4personal01",
    "joint": "acc_00009xJ4joint00001",
}

MERCHANTS = {
    "netflix": {"id": "merch_0000netflix001", "name": "Netflix", "category": "entertainment", "emoji": "🎬", "online": True, "atm": False},
    "spotify": {"id": "merch_0000spotify001", "name": "Spotify", "category": "entertainment", "emoji": "🎵", "online": True, "atm": False},
    "gym": {"id": "merch_0000puregym0001", "name": "PureGym", "category": "personal_care", "emoji": "💪", "online": False, "atm": False},
    "tesco": {"id": "merch_0000tesco00001", "name": "Tesco", "category": "groceries", "emoji": "🛒", "online": False, "atm": False},
    "sainsburys": {"id": "merch_0000sainsburys1", "name": "Sainsbury's", "category": "groceries", "emoji": "🛒", "online": False, "atm": False},
    "aldi": {"id": "merch_0000aldi000001", "name": "Aldi", "category": "groceries", "emoji": "🛒", "online": False, "atm": False},
    "costa": {"id": "merch_0000costa00001", "name": "Costa Coffee", "category": "eating_out", "emoji": "☕", "online": False, "atm": False},
    "pret": {"id": "merch_0000pret000001", "name": "Pret A Manger", "category": "eating_out", "emoji": "🥪", "online": False, "atm": False},
    "tfl": {"id": "merch_0000tfl0000001", "name": "Transport for London", "category": "transport", "emoji": "🚇", "online": False, "atm": False},
    "uber": {"id": "merch_0000uber000001", "name": "Uber", "category": "transport", "emoji": "🚕", "online": True, "atm": False},
    "amazon": {"id": "merch_0000amazon0001", "name": "Amazon", "category": "shopping", "emoji": "📦", "online": True, "atm": False},
    "boots": {"id": "merch_0000boots00001", "name": "Boots", "category": "shopping", "emoji": "💊", "online": False, "atm": False},
    "council": {"id": "merch_0000council001", "name": "Local Council Tax", "category": "bills", "emoji": "🏛️", "online": False, "atm": False},
}


def merchant(key):
    m = MERCHANTS[key]
    return {
        "id": m["id"],
        "name": m["name"],
        "category": m["category"],
        "emoji": m["emoji"],
        "online": m["online"],
        "atm": m["atm"],
    }


def txn(id, account, created, amount, category, description, merchant_key=None,
        notes="", settled=True, decline_reason=None, source="webhook"):
    settled_ts = created.replace(hour=(created.hour + 1) % 24) if settled else None
    return {
        "source": source,
        "transaction": {
            "id": id,
            "account_id": ACCOUNTS[account],
            "amount": amount,
            "currency": "GBP",
            "created": _iso(created),
            "settled": _iso(settled_ts) if settled_ts else None,
            "description": description,
            "category": category,
            "notes": notes,
            "is_load": False,
            "decline_reason": decline_reason,
            "merchant": merchant(merchant_key) if merchant_key else None,
        },
    }


class _D:
    """Tiny fixed-fields date/time holder so we don't need a datetime import for arithmetic."""
    def __init__(self, year, month, day, hour=12, minute=0):
        self.year, self.month, self.day, self.hour, self.minute = year, month, day, hour, minute

    def replace(self, **kw):
        f = dict(year=self.year, month=self.month, day=self.day, hour=self.hour, minute=self.minute)
        f.update(kw)
        return _D(**f)


def _iso(d):
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}T{d.hour:02d}:{d.minute:02d}:00Z"


def build_month(month, seq_offset):
    """One month (Jan/Feb/Mar 2026) of recurring + variable transactions."""
    n = seq_offset
    rows = []

    def add(*args, **kwargs):
        nonlocal n
        n += 1
        rows.append((f"tx_syn{n:05d}", txn(f"tx_syn{n:05d}", *args, **kwargs)))

    # Recurring monthly
    add("personal", _D(2026, month, 25, 9, 0), 285000, "income", "SALARY ACME CORP")
    add("personal", _D(2026, month, 1, 6, 0), -95000, "bills", "RENT LANDLORD LTD")
    add("personal", _D(2026, month, 5, 8, 15), -999, "entertainment", "NETFLIX.COM", "netflix", notes="Netflix")
    add("personal", _D(2026, month, 7, 19, 30), -1099, "entertainment", "SPOTIFY", "spotify", notes="Spotify")
    add("personal", _D(2026, month, 3, 7, 0), -3500, "personal_care", "PUREGYM LONDON", "gym")

    # Groceries (rotating merchant, amount varies month to month like real spend does -
    # otherwise mart_subscriptions' same-amount heuristic would misclassify these as subscriptions)
    month_drift = (month - 1) * 137
    grocery_merchants = ["tesco", "sainsburys", "aldi"]
    for i, day in enumerate((6, 14, 22)):
        m = grocery_merchants[i % len(grocery_merchants)]
        base = [4231, 5876, 3102][i]
        add("personal", _D(2026, month, day, 18, 0), -(base + month_drift + i * 29), "groceries",
            f"{MERCHANTS[m]['name'].upper()} STORES", m)

    # Eating out
    for i, day in enumerate((9, 20)):
        m = "costa" if i % 2 == 0 else "pret"
        base = [395, 650][i]
        add("personal", _D(2026, month, day, 8, 30), -(base + month_drift // 4), "eating_out",
            f"{MERCHANTS[m]['name'].upper()}", m)

    # Transport
    for i, day in enumerate((10, 24)):
        m = "tfl" if i % 2 == 0 else "uber"
        base = [290, 1180][i]
        add("personal", _D(2026, month, day, 17, 45), -(base + month_drift // 5), "transport",
            f"{MERCHANTS[m]['name'].upper()}", m)

    # Shopping - one-off, deliberately not a fixed amount month to month
    add("personal", _D(2026, month, 15, 21, 0), -(2999 + month_drift), "shopping", "AMAZON.CO.UK", "amazon")

    # Joint account - council tax is a genuine fixed monthly bill; the joint grocery run varies
    add("joint", _D(2026, month, 6, 18, 30), -(6742 + month_drift), "groceries", "SAINSBURYS SUPERSTORE", "sainsburys")
    add("joint", _D(2026, month, 1, 6, 0), -18500, "bills", "COUNCIL TAX", "council")

    return rows, n


def main():
    seq = 0
    all_rows = []
    extras = []

    for month in (1, 2, 3):
        rows, seq = build_month(month, seq)
        all_rows.extend(rows)

    # One declined transaction (Feb) - not a normal spend, tests settled/decline_reason handling
    seq += 1
    declined_id = f"tx_syn{seq:05d}"
    all_rows.append((declined_id, txn(
        declined_id, "personal", _D(2026, 2, 18, 12, 0), -18999, "shopping",
        "AMAZON.CO.UK", "amazon", settled=False, decline_reason="INSUFFICIENT_FUNDS",
    )))

    # One Boots purchase (Feb only) so dim_merchant/mart_merchant_summary has a long-tail merchant
    seq += 1
    boots_id = f"tx_syn{seq:05d}"
    all_rows.append((boots_id, txn(
        boots_id, "personal", _D(2026, 2, 12, 13, 0), -1450, "shopping", "BOOTS", "boots",
    )))

    for txn_id, payload in all_rows:
        created = payload["transaction"]["created"]
        y, m, d = created[0:4], created[5:7], created[8:10]
        out_dir = FIXTURES_ROOT / y / m / d
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{txn_id}.json").write_text(json.dumps(payload, indent=2) + "\n")

    print(f"Wrote {len(all_rows)} fixture files under {FIXTURES_ROOT}")


if __name__ == "__main__":
    main()
