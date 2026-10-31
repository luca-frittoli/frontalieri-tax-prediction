"""Run with: pytest -q   (uses a synthetic tariff file, NOT real rates)"""
import os
from pathlib import Path

FAKE = Path(__file__).parent / "fake_tar26ti.txt"


def _make_fake_file():
    lines = ["00TI" + " " * 15 + "20251208"]
    for code in ["R0N", "S0N", "S2N", "T0N", "U1N"]:
        for inc in range(1, 100001, 500):
            rate = min(int(inc / 100000 * 2000) + 100, 2400)
            lines.append(f"0601TI{code:<10}20260101{inc*100:09d}{50000:09d} "
                         f"{int(code[1]):02d}{0:09d}{rate:05d}   ")
    FAKE.write_text("\n".join(lines) + "\n", encoding="latin-1")


_make_fake_file()
os.environ["QST_TARIFF_FILE"] = str(FAKE)

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def test_chf_and_eur_inputs_agree():
    a = client.post("/compute", json={"gross_salary": 100_000, "currency": "CHF"}).json()
    b = client.post("/compute", json={"gross_salary": 108_000, "currency": "EUR",
                                      "eur_per_chf": 1.08}).json()
    assert abs(a["summary"]["net_salary_chf"] - b["summary"]["net_salary_chf"]) < 0.01


def test_get_endpoint_and_defaults():
    r = client.get("/compute", params={"gross_salary": 80_000})
    assert r.status_code == 200
    assert r.json()["switzerland_chf"]["withholding_tax"]["tariff_code"] == "R0N"


def test_override_and_validation():
    r = client.post("/compute", json={"gross_salary": 80_000, "withholding_tax_chf_override": 5000})
    assert r.json()["summary"]["swiss_withholding_tax_chf"] == 5000
    assert client.post("/compute", json={"gross_salary": 80_000,
                                         "employer_share_2nd_pillar": 0.3}).status_code == 422
    assert client.post("/compute", json={"gross_salary": 80_000,
                                         "salary_payments": 14}).status_code == 422
