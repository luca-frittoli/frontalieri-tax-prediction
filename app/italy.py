"""
Italian IRPEF 2026 for a "nuovo frontaliere" resident in Lombardy and working
in Ticino. All amounts in EUR (convert CHF at the exchange rate the Agenzia
delle Entrate accepts for the year).
"""

from math import inf

# IRPEF 2026 (L. 199/2025): 23% / 33% / 43%
SCAGLIONI_IRPEF = [(28_000, 0.23), (50_000, 0.33), (inf, 0.43)]

# Addizionale regionale Lombardia: progressive by bracket, like IRPEF itself
ADD_REGIONALE_LOMBARDIA = [(15_000, 0.0123), (28_000, 0.0158), (50_000, 0.0172), (inf, 0.0173)]

FRANCHIGIA_FRONTALIERI = 10_000  # first EUR 10k of the Swiss salary are exempt


def _progressiva(imponibile: float, scaglioni) -> float:
    """Each rate applies only to the slice of income inside its bracket."""
    tax, lower = 0.0, 0.0
    for upper, rate in scaglioni:
        if imponibile <= lower:
            break
        tax += (min(imponibile, upper) - lower) * rate
        lower = upper
    return tax


def irpef_lorda(imponibile: float) -> float:
    return _progressiva(imponibile, SCAGLIONI_IRPEF)


def addizionale_regionale(imponibile: float, scaglioni=ADD_REGIONALE_LOMBARDIA) -> float:
    return _progressiva(imponibile, scaglioni)


def addizionale_comunale(imponibile: float, aliquota: float = 0.008,
                         soglia_esenzione: float = 10_000) -> float:
    """An exemption threshold, not an allowance: above it the whole income is taxed."""
    return 0.0 if imponibile <= soglia_esenzione else imponibile * aliquota


def detrazione_lavoro_dipendente(reddito_complessivo: float, giorni: int = 365,
                                 tempo_determinato: bool = False) -> float:
    """Art. 13 TUIR, 2026."""
    rc = reddito_complessivo
    quota = giorni / 365
    if rc <= 15_000:
        minimo = 1_380 if tempo_determinato else 690
        d = max(1_955 * quota, minimo)
    elif rc <= 28_000:
        d = (1_910 + 1_190 * (28_000 - rc) / 13_000) * quota
    elif rc <= 50_000:
        d = 1_910 * (50_000 - rc) / 22_000 * quota
    else:
        d = 0.0
    if 25_000 < rc <= 35_000:
        d += 65
    return d


def ulteriore_detrazione_cuneo(reddito_complessivo: float) -> float:
    """Cuneo fiscale (L. 207/2024), for reddito complessivo between 20k and 40k."""
    rc = reddito_complessivo
    if 20_000 < rc <= 32_000:
        return 1_000.0
    if 32_000 < rc <= 40_000:
        return 1_000 * (40_000 - rc) / 8_000
    return 0.0


def somma_non_imponibile_cuneo(reddito_complessivo: float, reddito_lavoro: float) -> float:
    """Cuneo fiscale bonus for reddito complessivo up to 20k (a payment, not a tax cut)."""
    if reddito_complessivo > 20_000:
        return 0.0
    if reddito_lavoro <= 8_500:
        return reddito_lavoro * 0.071
    if reddito_lavoro <= 15_000:
        return reddito_lavoro * 0.053
    return reddito_lavoro * 0.048


def irpef_frontaliere(
    salario_lordo: float,
    contributi_obbligatori: float,
    imposta_fonte_ch: float,
    aliquota_comunale: float = 0.008,
    soglia_esenzione_comunale: float = 10_000,
    applica_cuneo: bool = True,
) -> dict:
    """
    salario_lordo          : Swiss gross salary, in EUR
    contributi_obbligatori : Swiss mandatory contributions (AVS/AI/IPG, AD, LPP), EUR
    imposta_fonte_ch       : Swiss withholding tax actually paid, EUR
    """
    reddito_estero = max(0.0, salario_lordo - contributi_obbligatori)
    reddito = max(0.0, reddito_estero - FRANCHIGIA_FRONTALIERI)

    lorda = irpef_lorda(reddito)
    detrazioni = detrazione_lavoro_dipendente(reddito)
    if applica_cuneo:
        detrazioni += ulteriore_detrazione_cuneo(reddito)
    netta = max(0.0, lorda - detrazioni)

    # Art. 165 c.10 TUIR: only part of the salary is taxed in Italy (franchigia),
    # so only the same share of the Swiss tax is creditable.
    quota_tassata = reddito / reddito_estero if reddito_estero else 0.0
    credito = min(imposta_fonte_ch * quota_tassata, netta)
    irpef_dovuta = netta - credito

    # The addizionali are due only if some IRPEF is due after detrazioni and the
    # foreign-tax credit.
    if irpef_dovuta > 0:
        add_reg = addizionale_regionale(reddito)
        add_com = addizionale_comunale(reddito, aliquota_comunale, soglia_esenzione_comunale)
    else:
        add_reg = add_com = 0.0

    bonus = somma_non_imponibile_cuneo(reddito, reddito) if applica_cuneo else 0.0
    totale = irpef_dovuta + add_reg + add_com - bonus
    return {
        "reddito_imponibile": round(reddito, 2),
        "irpef_lorda": round(lorda, 2),
        "detrazioni": round(detrazioni, 2),
        "irpef_netta_prima_del_credito": round(netta, 2),
        "credito_imposta_svizzera": round(credito, 2),
        "irpef_dovuta": round(irpef_dovuta, 2),
        "addizionale_regionale": round(add_reg, 2),
        "addizionale_comunale": round(add_com, 2),
        "bonus_cuneo": round(bonus, 2),
        "totale_italia": round(totale, 2),
    }
