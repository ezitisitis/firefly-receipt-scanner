"""Match scanned receipts against withdrawals that already exist in Firefly III."""

from datetime import date, timedelta

import requests

from .config import get_settings
from .firefly import get_account_withdrawals

# Rates per (base currency, day), kept for the lifetime of the process
_rates = {}

# Upper bound of candidates shown per receipt
MAX_CANDIDATES = 10


def get_rate(from_currency, to_currency):
    """Exchange rate from one currency to another, or None if unavailable."""
    if not from_currency or not to_currency:
        return None
    if from_currency == to_currency:
        return 1.0
    url = get_settings().fx_rates_url
    if not url:
        return None
    key = (from_currency, date.today())
    if key not in _rates:
        try:
            response = requests.get(url.format(base=from_currency), timeout=10)
            response.raise_for_status()
            _rates[key] = response.json()["rates"]
        except Exception as e:
            print(f"Could not fetch exchange rates for {from_currency}: {e}")
            return None
    rate = _rates[key].get(to_currency)
    return float(rate) if rate else None


def convert(amount, from_currency, to_currency):
    rate = get_rate(from_currency, to_currency)
    return amount * rate if rate else None


def _compare(amount, currency, split, settings):
    """Return (difference, tolerance, reason); difference is None when amounts can't be compared."""
    if (
        currency
        and split["foreign_currency_code"] == currency
        and split["foreign_amount"] is not None
    ):
        diff = abs(split["foreign_amount"] - amount)
        reason = f"original amount {split['foreign_amount']:.2f} {currency}"
        return diff, settings.match_amount_tolerance, reason
    if not currency or not split["currency_code"] or split["currency_code"] == currency:
        diff = abs(split["amount"] - amount)
        reason = "same amount" if diff < 0.005 else "amount within tolerance"
        return diff, settings.match_amount_tolerance, reason
    expected = convert(amount, currency, split["currency_code"])
    if expected is None:
        return None, 0, f"date only, no {currency} exchange rate"
    diff = abs(split["amount"] - expected)
    tolerance = expected * settings.match_fx_tolerance_percent / 100
    reason = f"≈ {expected:.2f} {split['currency_code']} converted from {currency}"
    return diff, tolerance, reason


def find_matches(receipt, account, window_days):
    """Withdrawals from `account` within ±window_days whose amount fits the receipt, best first."""
    settings = get_settings()
    try:
        day = date.fromisoformat(receipt["date"])
        amount = float(receipt["amount"])
        splits = get_account_withdrawals(
            account["id"],
            (day - timedelta(days=window_days)).isoformat(),
            (day + timedelta(days=window_days)).isoformat(),
        )
    except Exception as e:
        print(f"Could not look up existing transactions: {e}")
        return []

    currency = (receipt.get("currency") or "").upper()
    candidates = []
    for split in splits:
        diff, tolerance, reason = _compare(amount, currency, split, settings)
        if diff is not None and diff > tolerance + 0.005:
            continue
        candidates.append(
            {
                **split,
                "days": abs((date.fromisoformat(split["date"]) - day).days),
                "diff": diff,
                "reason": reason,
                "has_receipt": split["has_attachments"] or "automated" in split["tags"],
            }
        )
    # Comparable amounts first, exact ones before approximate, then the closest date
    candidates.sort(
        key=lambda c: (c["diff"] is None, (c["diff"] or 0) >= 0.005, c["days"], c["diff"] or 0)
    )
    return candidates[:MAX_CANDIDATES]


def assign_matches(receipts):
    """Preselect the best amount-matched candidate per receipt, never the same one twice."""
    taken = set()
    for receipt in receipts:
        receipt["selected_match"] = "new"
        for candidate in receipt.get("candidates", []):
            if candidate["diff"] is not None and candidate["journal_id"] not in taken:
                taken.add(candidate["journal_id"])
                receipt["selected_match"] = (
                    f"{candidate['group_id']}:{candidate['journal_id']}"
                )
                break
