# Frontalieri Ticino calculator (2026)

Local REST API that, for a **new frontaliere** or **old frontaliere fuori fascia** (resident in Lombardy, commuting daily
to Ticino, taxed in both countries) computes:

1. Swiss employee contributions: AVS/AI/IPG, AD, LPP legal minimum (CHF)
2. Swiss withholding tax with Ticino tariffs R/S/T/U (CHF)
3. Italian IRPEF + addizionali, net of the €10k franchigia and the credit for the Swiss tax (EUR)

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Put the official Ticino tariff file in `data/tar26ti.zip`. Download it from the AFC/ESTV site:
"Quellensteuertarife für den Import in Lohnbuchhaltungssysteme", then Tessin, "Tarife 2026".
To use a different location, set `QST_TARIFF_FILE=/path/to/tar26ti.zip`.

```bash
uvicorn app.main:app --reload
```

Interactive docs: http://127.0.0.1:8000/docs

## Examples

```bash
curl -X POST http://127.0.0.1:8000/compute -H "Content-Type: application/json" \
  -d '{"gross_salary": 90000, "currency": "CHF", "age": 40, "salary_payments": 13}'

curl "http://127.0.0.1:8000/compute?gross_salary=70000&currency=EUR&marital_status=married_single_earner&children=2"
```

## Parameters (all optional except gross_salary)

| name | default | notes |
|---|---|---|
| gross_salary | — | yearly gross |
| currency | CHF | CHF or EUR |
| eur_per_chf | 1.08 | EUR for 1 CHF; env var `EUR_PER_CHF` changes the default. For the tax return use the rate the Agenzia delle Entrate accepts |
| age | 35 | calendar year minus birth year (drives LPP credits) |
| employer_share_2nd_pillar | 0.7 | between 0.5 and 1 |
| marital_status | single | single, married_single_earner, married_dual_earner, single_with_children |
| children | 0 | 0 to 9 |
| church | false | uses the "Y" tariff variant if present |
| salary_payments | 12 | 12 or 13 (13th paid in December) |
| withholding_tax_chf_override | null | yearly Swiss withholding to use instead of the tariff file |
| aliquota_comunale | 0.008 | your comune's addizionale |
| soglia_esenzione_comunale | 10000 | your comune's exemption threshold |
| applica_cuneo | true | Italian cuneo fiscale |

## Tests

`pytest -q` (uses a synthetic tariff file: its rates are fake).

## Limitations

- LPP: legal savings credits only (no risk/admin premiums of the actual pension fund).
- Not included: non-occupational accident insurance, Italian family deductions,
  other incomes, telework days.
- Points worth confirming with a CAF/patronato: whether the Swiss contributions are
  treated as a reduction of income or as oneri deducibili, the art. 165 c.10
  reduction of the Swiss tax credit, and whether the cuneo applies to frontalieri.
