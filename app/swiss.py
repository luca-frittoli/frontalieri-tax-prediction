"""
Employee-side social contributions and Swiss withholding tax (imposta alla fonte)
for a NEW cross-border commuter ("nuovo frontaliere") who lives in Italy and
commutes daily to Canton Ticino. Year 2026.

"New" frontalieri (hired after 17 July 2023, or otherwise outside the
transitional regime of the 2020 CH-IT agreement) are taxed with the Ticino
tariffs R, S, T, U, which already embed the 80% share kept by Switzerland.
They are also taxed in Italy (IRPEF), which credits the Swiss tax; that part
is NOT computed here.

The withholding rates are not hard-coded: Ticino publishes ~10k rate rows per
year. Download the official file from the AFC/ESTV ("Quellensteuertarife für
den Import in Lohnbuchhaltungssysteme" -> Tessin -> Tarife 2026), i.e.
tar26ti.zip / tar26ti.txt, and pass its path to compute_withholding_tax().

"age" means calendar year minus birth year, which is how AVS/LPP count it.
"""

from __future__ import annotations

import io
import zipfile
from bisect import bisect_right
from functools import lru_cache

# ---------------------------------------------------------------------------
# 1st pillar (AVS/AI/IPG) and unemployment insurance (AD) - 2026
# ---------------------------------------------------------------------------
AHV_RATE_EMPLOYEE = 0.053        # AVS 4.35% + AI 0.70% + IPG 0.25%
AHV_RETIREE_ALLOWANCE = 16_800   # yearly franchise for workers past reference age
ALV_RATE_EMPLOYEE = 0.011        # AD, on salary up to the ceiling
ALV_CEILING = 148_200
REFERENCE_AGE = 65

# ---------------------------------------------------------------------------
# 2nd pillar - LPP/BVG mandatory minimum - 2026
# ---------------------------------------------------------------------------
BVG_ENTRY_THRESHOLD = 22_680
BVG_COORDINATION_DEDUCTION = 26_460
BVG_UPPER_LIMIT = 90_720
BVG_MIN_COORDINATED = 3_780
BVG_AGE_CREDITS = [  # (min age, max age, savings credit on coordinated salary)
    (25, 34, 0.07),
    (35, 44, 0.10),
    (45, 54, 0.15),
    (55, 65, 0.18),
]

def compute_pension_contributions(
    gross_salary: float,
    age: int,
    employer_share_2nd_pillar: float = 0.7,
    include_unemployment: bool = True,
) -> dict:
    """
    Employee contributions to the 1st pillar (AVS/AI/IPG) and to the
    mandatory-minimum 2nd pillar (LPP), plus unemployment insurance (AD),
    which is withheld together with the 1st pillar on every payslip.

    The 1st pillar is split 50/50 by law. For the 2nd pillar the employer must
    pay at least half (art. 66 LPP), so employer_share_2nd_pillar is in [0.5, 1].
    Only the legal savings credits are modelled: pension funds add risk and
    admin contributions whose size is set by each fund, not by law.
    """
    if gross_salary < 0:
        raise ValueError("gross_salary must be non-negative")
    if not 0.5 <= employer_share_2nd_pillar <= 1.0:
        raise ValueError("employer_share_2nd_pillar must be between 0.5 and 1.0 (art. 66 LPP)")

    # 1st pillar: due from the year a person turns 18; past reference age a
    # yearly allowance is exempt.
    if age < 18:
        ahv_base = 0.0
    elif age > REFERENCE_AGE:
        ahv_base = max(0.0, gross_salary - AHV_RETIREE_ALLOWANCE)
    else:
        ahv_base = gross_salary
    ahv = ahv_base * AHV_RATE_EMPLOYEE

    # Unemployment insurance: not due past reference age.
    alv = 0.0
    if include_unemployment and 18 <= age <= REFERENCE_AGE:
        alv = min(gross_salary, ALV_CEILING) * ALV_RATE_EMPLOYEE

    # 2nd pillar savings credits: from the year a person turns 25.
    coordinated_salary, credit_rate = 0.0, 0.0
    if gross_salary > BVG_ENTRY_THRESHOLD:
        for lo, hi, rate in BVG_AGE_CREDITS:
            if lo <= age <= hi:
                credit_rate = rate
                coordinated_salary = max(
                    min(gross_salary, BVG_UPPER_LIMIT) - BVG_COORDINATION_DEDUCTION,
                    BVG_MIN_COORDINATED,
                )
                break
    bvg_total = coordinated_salary * credit_rate
    bvg_employee = bvg_total * (1 - employer_share_2nd_pillar)

    return {
        "ahv_iv_eo": round(ahv, 2),
        "alv": round(alv, 2),
        "bvg_coordinated_salary": round(coordinated_salary, 2),
        "bvg_credit_rate": credit_rate,
        "bvg_total": round(bvg_total, 2),
        "bvg_employee": round(bvg_employee, 2),
        "bvg_employer": round(bvg_total - bvg_employee, 2),
        "employee_total": round(ahv + alv + bvg_employee, 2),
    }


# ---------------------------------------------------------------------------
# Swiss withholding tax for new Italian frontalieri (tariffs R, S, T, U)
# ---------------------------------------------------------------------------
FRONTALIERI_TARIFF_LETTER = {
    "single": "R",                 # like A: single, no children
    "married_single_earner": "S",  # like B
    "married_dual_earner": "T",    # like C
    "single_with_children": "U",   # like H: single living with dependent children
}


@lru_cache(maxsize=4)
def load_withholding_tariffs(path: str) -> dict[str, tuple[list, list]]:
    """
    Parse an AFC/ESTV withholding-tariff file (tarJJkt.txt or tarJJkt.zip).

    Record type 06, fixed width (positions are 1-based in the AFC spec):
      07-16 tariff code, 25-33 monthly income from (CHF, 2 implied decimals),
      34-42 bracket width, 44-45 children, 46-54 minimum tax, 55-59 rate %.
    Returns {code: (incomes_from, [(min_tax, rate_pct), ...])}, sorted.
    """
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
            raw = zf.read(name)
    else:
        with open(path, "rb") as f:
            raw = f.read()

    rows: dict[str, list] = {}
    for line in io.TextIOWrapper(io.BytesIO(raw), encoding="latin-1"):
        if not line.startswith("06") or line[2:4] == "03":  # 03 = deleted record
            continue
        code = line[6:16].strip()
        income_from = int(line[24:33]) / 100
        min_tax = int(line[45:54]) / 100
        rate_pct = int(line[54:59]) / 100
        rows.setdefault(code, []).append((income_from, min_tax, rate_pct))

    tariffs = {}
    for code, recs in rows.items():
        recs.sort()
        tariffs[code] = ([r[0] for r in recs], [(r[1], r[2]) for r in recs])
    return tariffs


def _monthly_withholding(monthly_income: float, table: tuple[list, list]) -> tuple[float, float]:
    """Tax and rate (%) for one month; the rate applies to the whole income."""
    incomes_from, values = table
    if monthly_income <= 0:
        return 0.0, 0.0
    i = max(bisect_right(incomes_from, monthly_income) - 1, 0)
    min_tax, rate_pct = values[i]
    return max(monthly_income * rate_pct / 100, min_tax), rate_pct


def compute_withholding_tax(
    gross_salary: float,
    tariff_file: str,
    marital_status: str = "single",
    children: int = 0,
    church: bool = False,
    salary_payments: int = 12,
) -> dict:
    """
    Yearly Swiss withholding tax of a new Italian frontaliere working in Ticino.

    gross_salary    : yearly gross salary (the AVS salary, before contributions;
                      withholding is applied to gross, contributions are not
                      deducted).
    marital_status  : "single", "married_single_earner", "married_dual_earner"
                      or "single_with_children".
    salary_payments : 12, or 13 if a 13th salary is paid. Under the monthly
                      model the 13th is added to the month it is paid
                      (assumed December), so that month gets a higher rate.
    church          : use the "Y" (with church tax) variant if the file has it.
    """
    if marital_status not in FRONTALIERI_TARIFF_LETTER:
        raise ValueError(f"marital_status must be one of {list(FRONTALIERI_TARIFF_LETTER)}")
    if salary_payments not in (12, 13):
        raise ValueError("salary_payments must be 12 or 13")
    if marital_status == "single" and children > 0:
        marital_status = "single_with_children"
    if marital_status == "single_with_children" and children < 1:
        raise ValueError("tariff U requires at least one child")

    letter = FRONTALIERI_TARIFF_LETTER[marital_status]
    code = f"{letter}{min(children, 9)}{'Y' if church else 'N'}"
    tariffs = load_withholding_tariffs(tariff_file)
    if code not in tariffs:
        available = sorted(c for c in tariffs if c.startswith(letter))
        raise KeyError(f"tariff {code} not in file; available: {available}")
    table = tariffs[code]

    monthly = gross_salary / salary_payments
    regular_tax, regular_rate = _monthly_withholding(monthly, table)
    if salary_payments == 13:
        december_tax, december_rate = _monthly_withholding(2 * monthly, table)
        total = 11 * regular_tax + december_tax
    else:
        december_tax, december_rate = regular_tax, regular_rate
        total = 12 * regular_tax

    return {
        "tariff_code": code,
        "monthly_gross": round(monthly, 2),
        "monthly_rate_pct": regular_rate,
        "monthly_tax": round(regular_tax, 2),
        "december_rate_pct": december_rate,
        "december_tax": round(december_tax, 2),
        "total_withholding_tax": round(total, 2),
        "effective_rate_on_gross": round(total / gross_salary, 4) if gross_salary else 0.0,
    }
