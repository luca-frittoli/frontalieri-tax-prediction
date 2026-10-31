"""
Local API: Swiss contributions + Ticino withholding tax + Italian IRPEF
for a new Italian frontaliere working in Ticino (tax year 2026).

Run:  uvicorn app.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import italy, swiss

TARIFF_FILE = os.environ.get(
    "QST_TARIFF_FILE", str(Path(__file__).resolve().parent.parent / "data" / "tar26ti.zip")
)
DEFAULT_EUR_PER_CHF = float(os.environ.get("EUR_PER_CHF", "1.08"))

app = FastAPI(
    title="Frontalieri Ticino calculator",
    version="1.0.0",
    description="Swiss contributions and withholding tax, then Italian IRPEF, "
                "for a new frontaliere resident in Lombardy working in Ticino (2026).",
)


class Currency(str, Enum):
    CHF = "CHF"
    EUR = "EUR"


class MaritalStatus(str, Enum):
    single = "single"
    married_single_earner = "married_single_earner"
    married_dual_earner = "married_dual_earner"
    single_with_children = "single_with_children"


class CalcRequest(BaseModel):
    gross_salary: float = Field(..., gt=0, description="Yearly gross salary")
    currency: Currency = Field(Currency.CHF, description="Currency of gross_salary")
    eur_per_chf: float = Field(DEFAULT_EUR_PER_CHF, gt=0,
                               description="Exchange rate used for conversions (EUR for 1 CHF)")

    # Swiss side
    age: int = Field(35, ge=15, le=75, description="Calendar year minus birth year")
    employer_share_2nd_pillar: float = Field(0.7, ge=0.5, le=1.0)
    marital_status: MaritalStatus = MaritalStatus.single
    children: int = Field(0, ge=0, le=9)
    church: bool = False
    salary_payments: int = Field(12, description="12, or 13 if a 13th salary is paid")
    withholding_tax_chf_override: Optional[float] = Field(
        None, ge=0, description="Use this yearly Swiss withholding tax instead of the tariff file")

    # Italian side
    aliquota_comunale: float = Field(0.008, ge=0, le=0.009)
    soglia_esenzione_comunale: float = Field(10_000, ge=0)
    applica_cuneo: bool = True


def _compute(req: CalcRequest) -> dict:
    if req.salary_payments not in (12, 13):
        raise HTTPException(422, "salary_payments must be 12 or 13")

    gross_chf = req.gross_salary if req.currency == Currency.CHF else req.gross_salary / req.eur_per_chf

    contributions = swiss.compute_pension_contributions(
        gross_chf, req.age, req.employer_share_2nd_pillar)

    if req.withholding_tax_chf_override is not None:
        withholding = {"source": "override",
                       "total_withholding_tax": round(req.withholding_tax_chf_override, 2)}
    else:
        if not Path(TARIFF_FILE).exists():
            raise HTTPException(
                503,
                f"Tariff file not found at {TARIFF_FILE}. Download 'Tarife 2026' for Tessin from "
                "the AFC/ESTV site (Quellensteuertarife für den Import in Lohnbuchhaltungssysteme), "
                "or pass withholding_tax_chf_override.")
        try:
            withholding = swiss.compute_withholding_tax(
                gross_chf, TARIFF_FILE, req.marital_status.value, req.children,
                req.church, req.salary_payments)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, str(e))
        withholding["source"] = "tariff_file"

    contrib_chf = contributions["employee_total"]
    withholding_chf = withholding["total_withholding_tax"]
    fx = req.eur_per_chf

    italian = italy.irpef_frontaliere(
        salario_lordo=gross_chf * fx,
        contributi_obbligatori=contrib_chf * fx,
        imposta_fonte_ch=withholding_chf * fx,
        aliquota_comunale=req.aliquota_comunale,
        soglia_esenzione_comunale=req.soglia_esenzione_comunale,
        applica_cuneo=req.applica_cuneo,
    )

    net_chf = gross_chf - contrib_chf - withholding_chf - italian["totale_italia"] / fx
    return {
        "inputs": req.model_dump(mode="json"),
        "gross": {"chf": round(gross_chf, 2), "eur": round(gross_chf * fx, 2)},
        "switzerland_chf": {"contributions": contributions, "withholding_tax": withholding},
        "italy_eur": italian,
        "summary": {
            "swiss_contributions_chf": round(contrib_chf, 2),
            "swiss_withholding_tax_chf": round(withholding_chf, 2),
            "italian_taxes_eur": italian["totale_italia"],
            "net_salary_chf": round(net_chf, 2),
            "net_salary_eur": round(net_chf * fx, 2),
            "net_monthly_eur_12": round(net_chf * fx / 12, 2),
            "total_deductions_rate": round(1 - net_chf / gross_chf, 4),
        },
    }


@app.get("/health")
def health():
    return {"status": "ok", "tariff_file": TARIFF_FILE, "tariff_file_found": Path(TARIFF_FILE).exists()}


@app.post("/compute")
def compute_post(req: CalcRequest):
    return _compute(req)


@app.get("/compute")
def compute_get(req: CalcRequest = Depends()):
    """Same as POST, with parameters in the query string."""
    return _compute(req)
