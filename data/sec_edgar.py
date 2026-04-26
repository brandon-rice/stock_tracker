"""SEC EDGAR XBRL backfill — free historical quarterly financials.

Fills gaps yfinance can't cover: it only returns ~5 quarters, but YOY
growth needs the prior-year same quarter. EDGAR has 5+ years of data.
"""
import requests
from datetime import datetime
from sqlalchemy.dialects.postgresql import insert
from db.connection import get_sessions
from db.models import Financials, Stock

from config import REPORT_RECIPIENT_EMAIL

USER_AGENT = f"Brandon Rice Stock Tracker {REPORT_RECIPIENT_EMAIL}"

# Fallback concept lists — different companies use different XBRL tags
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]
NET_INCOME_CONCEPTS = ["NetIncomeLoss"]
EPS_CONCEPTS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]
OCF_CONCEPTS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
CAPEX_CONCEPTS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]


def _get_cik(ticker: str) -> str | None:
    resp = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    for entry in resp.json().values():
        if entry["ticker"].upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    return None


def _get_company_facts(cik: str) -> dict:
    resp = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _is_single_quarter(row: dict) -> bool:
    """A single fiscal quarter is ~3 months (80-100 days). YTD entries are longer."""
    start, end = row.get("start"), row.get("end")
    if not start or not end:
        return True  # instantaneous values (EPS, balance sheet items)
    try:
        d1 = datetime.fromisoformat(start)
        d2 = datetime.fromisoformat(end)
        days = (d2 - d1).days
        return 80 <= days <= 100
    except Exception:
        return False


def _extract_concept(us_gaap: dict, concepts: list[str], duration: str = "quarter") -> dict[tuple[int, int], float]:
    """Returns {(fy, q): value}. duration='quarter' filters to ~3-month periods."""
    for c in concepts:
        if c not in us_gaap:
            continue
        units = us_gaap[c].get("units", {})
        unit_key = next((k for k in units if k.startswith("USD")), None)
        if not unit_key:
            continue
        result = {}
        for row in units[unit_key]:
            fy, fp = row.get("fy"), row.get("fp")
            if fp not in ("Q1", "Q2", "Q3", "Q4"):
                continue
            if duration == "quarter" and not _is_single_quarter(row):
                continue
            q = int(fp[1])
            existing = result.get((fy, q))
            if not existing or row["filed"] > existing["filed"]:
                result[(fy, q)] = {"val": float(row["val"]), "filed": row["filed"]}
        return {k: v["val"] for k, v in result.items()}
    return {}


def _extract_quarterly_q4_from_annual(us_gaap: dict, concepts: list[str], q123: dict) -> dict:
    """If Q4 wasn't reported separately, compute it as FY - (Q1 + Q2 + Q3)."""
    annual = {}
    for c in concepts:
        if c not in us_gaap:
            continue
        units = us_gaap[c].get("units", {})
        unit_key = next((k for k in units if k.startswith("USD")), None)
        if not unit_key:
            continue
        for row in units[unit_key]:
            if row.get("fp") != "FY":
                continue
            # Annual entries should span ~365 days
            start, end = row.get("start"), row.get("end")
            if start and end:
                try:
                    days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
                    if not (340 <= days <= 380):
                        continue
                except Exception:
                    continue
            fy = row.get("fy")
            existing = annual.get(fy)
            if not existing or row["filed"] > existing["filed"]:
                annual[fy] = {"val": float(row["val"]), "filed": row["filed"]}
        break

    q4 = {}
    for fy, fy_row in annual.items():
        if (fy, 4) in q123:  # already have it from a 10-Q
            continue
        q1 = q123.get((fy, 1))
        q2 = q123.get((fy, 2))
        q3 = q123.get((fy, 3))
        if q1 is not None and q2 is not None and q3 is not None:
            q4[(fy, 4)] = fy_row["val"] - q1 - q2 - q3
    return q4


def backfill_from_sec(ticker: str) -> int:
    """Backfill quarterly financials from SEC EDGAR. Returns number of rows upserted."""
    ticker = ticker.upper()
    cik = _get_cik(ticker)
    if not cik:
        print(f"SEC EDGAR: no CIK found for {ticker}")
        return 0

    facts = _get_company_facts(cik)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    revenue = _extract_concept(us_gaap, REVENUE_CONCEPTS)
    net_income = _extract_concept(us_gaap, NET_INCOME_CONCEPTS)
    eps = _extract_concept(us_gaap, EPS_CONCEPTS, duration="any")
    ocf = _extract_concept(us_gaap, OCF_CONCEPTS)
    capex = _extract_concept(us_gaap, CAPEX_CONCEPTS)

    # Backfill missing Q4 from FY annual data
    revenue.update(_extract_quarterly_q4_from_annual(us_gaap, REVENUE_CONCEPTS, revenue))
    net_income.update(_extract_quarterly_q4_from_annual(us_gaap, NET_INCOME_CONCEPTS, net_income))
    ocf.update(_extract_quarterly_q4_from_annual(us_gaap, OCF_CONCEPTS, ocf))
    capex.update(_extract_quarterly_q4_from_annual(us_gaap, CAPEX_CONCEPTS, capex))

    # Build per-quarter rows
    all_keys = set(revenue) | set(net_income) | set(eps) | set(ocf) | set(capex)
    rows = []
    for (fy, q) in sorted(all_keys, reverse=True):
        ops = ocf.get((fy, q))
        cap = capex.get((fy, q))
        fcf = float(ops - abs(cap)) if (ops is not None and cap is not None) else None
        rows.append({
            "fiscal_year": fy,
            "fiscal_quarter": q,
            "revenue": revenue.get((fy, q)),
            "net_income": net_income.get((fy, q)),
            "eps": eps.get((fy, q)),
            "free_cash_flow": fcf,
            "reported_date": None,
        })

    if not rows:
        print(f"SEC EDGAR: no quarterly data extracted for {ticker}")
        return 0

    def _store(session, stock_id, rows):
        for r in rows:
            stmt = insert(Financials).values(stock_id=stock_id, **r)
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "fiscal_year", "fiscal_quarter"],
                set_={k: v for k, v in r.items() if v is not None},
            )
            session.execute(stmt)

    with get_sessions() as (local, neon):
        local_stock = local.query(Stock).filter_by(ticker=ticker).first()
        neon_stock = neon.query(Stock).filter_by(ticker=ticker).first()
        if not local_stock:
            raise ValueError(f"{ticker} not in portfolio")
        _store(local, local_stock.id, rows)
        _store(neon, neon_stock.id, rows)

    return len(rows)
