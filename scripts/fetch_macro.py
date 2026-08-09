#!/usr/bin/env python3
"""
Hulbert Macro Screen — Data Fetcher v2
Fetches CPI and Unemployment for 43 country ETFs.

Estratégia híbrida:
  1. OECD SDMX API (mensal, corrente) para os 23 países-membros da OECD
  2. World Bank API (anual, com desfasamento) como reserva para os
     restantes 20 países e para qualquer falha pontual da OECD

P/E: mantém-se manual — o valor existente no hulbert_data.json é
preservado (este script nunca o sobrescreve).

Corre via GitHub Actions no dia 5 de cada mês (ver
.github/workflows/update_macro_data.yml).
"""

import json
import csv
import io
import os
import sys
import urllib.request
import urllib.error
import time
from datetime import datetime

# ── Universo de 43 países ────────────────────────────────────────────────────
# wb   = código World Bank (ISO alpha-2)
# oecd = código OECD SDMX (ISO alpha-3), ou None se não for membro OECD
COUNTRIES = [
    {"etf": "SPY",  "country": "United States",   "region": "North America",       "wb": "US", "oecd": "USA"},
    {"etf": "EWC",  "country": "Canada",           "region": "North America",       "wb": "CA", "oecd": "CAN"},
    {"etf": "EWG",  "country": "Germany",          "region": "Core Europe",         "wb": "DE", "oecd": "DEU"},
    {"etf": "EWQ",  "country": "France",           "region": "Core Europe",         "wb": "FR", "oecd": "FRA"},
    {"etf": "EWU",  "country": "United Kingdom",   "region": "Core Europe",         "wb": "GB", "oecd": "GBR"},
    {"etf": "EWL",  "country": "Switzerland",      "region": "Core Europe",         "wb": "CH", "oecd": "CHE"},
    {"etf": "EWN",  "country": "Netherlands",      "region": "Core Europe",         "wb": "NL", "oecd": "NLD"},
    {"etf": "EWO",  "country": "Austria",          "region": "Core Europe",         "wb": "AT", "oecd": "AUT"},
    {"etf": "EWI",  "country": "Italy",            "region": "Peripheral Europe",   "wb": "IT", "oecd": "ITA"},
    {"etf": "EWP",  "country": "Spain",            "region": "Peripheral Europe",   "wb": "ES", "oecd": "ESP"},
    {"etf": "GREK", "country": "Greece",           "region": "Peripheral Europe",   "wb": "GR", "oecd": "GRC"},
    {"etf": "EIRL", "country": "Ireland",          "region": "Peripheral Europe",   "wb": "IE", "oecd": "IRL"},
    {"etf": "EPOL", "country": "Poland",           "region": "Emerging Europe",     "wb": "PL", "oecd": "POL"},
    {"etf": "EWCZ", "country": "Czech Republic",   "region": "Emerging Europe",     "wb": "CZ", "oecd": "CZE"},
    {"etf": "TUR",  "country": "Turkey",           "region": "Emerging Europe",     "wb": "TR", "oecd": "TUR"},
    {"etf": "EWJ",  "country": "Japan",            "region": "Developed Asia",      "wb": "JP", "oecd": "JPN"},
    {"etf": "EWA",  "country": "Australia",        "region": "Developed Asia",      "wb": "AU", "oecd": "AUS"},
    {"etf": "ENZL", "country": "New Zealand",      "region": "Developed Asia",      "wb": "NZ", "oecd": "NZL"},
    {"etf": "EWS",  "country": "Singapore",        "region": "Developed Asia",      "wb": "SG", "oecd": None},
    {"etf": "EWH",  "country": "Hong Kong",        "region": "Developed Asia",      "wb": "HK", "oecd": None},
    {"etf": "MCHI", "country": "China",            "region": "Emerging Asia",       "wb": "CN", "oecd": None},
    {"etf": "EWY",  "country": "South Korea",      "region": "Emerging Asia",       "wb": "KR", "oecd": "KOR"},
    {"etf": "EWT",  "country": "Taiwan",           "region": "Emerging Asia",       "wb": "TW", "oecd": None},
    {"etf": "INDA", "country": "India",            "region": "Emerging Asia",       "wb": "IN", "oecd": None},
    {"etf": "EIDO", "country": "Indonesia",        "region": "Emerging Asia",       "wb": "ID", "oecd": None},
    {"etf": "EWM",  "country": "Malaysia",         "region": "Emerging Asia",       "wb": "MY", "oecd": None},
    {"etf": "THD",  "country": "Thailand",         "region": "Emerging Asia",       "wb": "TH", "oecd": None},
    {"etf": "EPHE", "country": "Philippines",      "region": "Emerging Asia",       "wb": "PH", "oecd": None},
    {"etf": "VNM",  "country": "Vietnam",          "region": "Emerging Asia",       "wb": "VN", "oecd": None},
    {"etf": "PAK",  "country": "Pakistan",         "region": "Emerging Asia",       "wb": "PK", "oecd": None},
    {"etf": "EWZ",  "country": "Brazil",           "region": "Latin America",       "wb": "BR", "oecd": None},
    {"etf": "EWW",  "country": "Mexico",           "region": "Latin America",  "wb": "MX", "oecd": "MEX"},
    {"etf": "ECH",  "country": "Chile",            "region": "Latin America",  "wb": "CL", "oecd": "CHL"},
    {"etf": "GXG",  "country": "Colombia",         "region": "Latin America",  "wb": "CO", "oecd": "COL"},
    {"etf": "EPU",  "country": "Peru",             "region": "Latin America",  "wb": "PE", "oecd": None},
    {"etf": "ARGT", "country": "Argentina",        "region": "Latin America",  "wb": "AR", "oecd": None},
    {"etf": "EIS",  "country": "Israel",           "region": "Middle East",    "wb": "IL", "oecd": "ISR"},
    {"etf": "KSA",  "country": "Saudi Arabia",     "region": "Middle East",    "wb": "SA", "oecd": None},
    {"etf": "UAE",  "country": "UAE",              "region": "Middle East",    "wb": "AE", "oecd": None},
    {"etf": "QAT",  "country": "Qatar",            "region": "Middle East",    "wb": "QA", "oecd": None},
    {"etf": "KWT",  "country": "Kuwait",           "region": "Middle East",    "wb": "KW", "oecd": None},
    {"etf": "EZA",  "country": "South Africa",     "region": "Africa",         "wb": "ZA", "oecd": None},
    {"etf": "EGPT", "country": "Egypt",            "region": "Africa",         "wb": "EG", "oecd": None},
]

TODAY = datetime.now().strftime("%Y-%m-%d")
OECD_BASE = "https://sdmx.oecd.org/public/rest/data"
WB_BASE = "https://api.worldbank.org/v2/country"

REPO_JSON_PATH = os.environ.get("HULBERT_JSON_PATH", "hulbert_data.json")


# ── OECD ──────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/vnd.sdmx.data+csv",
}


def fetch_oecd_csv(url, attempts=2):
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=35) as resp:
                text = resp.read().decode("utf-8")
            return list(csv.DictReader(io.StringIO(text)))
        except Exception as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(3)
    raise last_err


def get_oecd_cpi():
    """Devolve {oecd_code: (valor, data)} — CPI homólogo total, mensal."""
    url = (
        f"{OECD_BASE}/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/all"
        f"?startPeriod=2025-01&format=csvfilewithlabels"
    )
    try:
        rows = fetch_oecd_csv(url)
    except Exception as e:
        print(f"  [OECD CPI] falhou: {e}")
        return {}

    filtered = [
        r for r in rows
        if r.get("FREQ") == "M"
        and r.get("MEASURE") == "CPI"
        and r.get("UNIT_MEASURE") == "PA"
        and r.get("TRANSFORMATION") == "GY"
        and r.get("EXPENDITURE") == "_T"
    ]
    return _most_recent(filtered)


def get_oecd_unemployment():
    """Devolve {oecd_code: (valor, data)} — taxa de desemprego, 15+, ajustada, mensal."""
    url = (
        f"{OECD_BASE}/OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0/all"
        f"?startPeriod=2025-01&format=csvfilewithlabels"
    )
    try:
        rows = fetch_oecd_csv(url)
    except Exception as e:
        print(f"  [OECD Unemployment] falhou: {e}")
        return {}

    filtered = [
        r for r in rows
        if r.get("FREQ") == "M"
        and r.get("SEX") == "_T"
        and r.get("AGE") == "Y_GE15"
        and r.get("ADJUSTMENT") == "Y"
    ]
    result = _most_recent(filtered)
    if not result:
        # reserva: sem ajuste sazonal
        filtered = [
            r for r in rows
            if r.get("FREQ") == "M"
            and r.get("SEX") == "_T"
            and r.get("AGE") == "Y_GE15"
            and r.get("ADJUSTMENT") == "N"
        ]
        result = _most_recent(filtered)
    return result


def _most_recent(rows, area_col="REF_AREA", time_col="TIME_PERIOD", value_col="OBS_VALUE"):
    best = {}
    for row in rows:
        area = row.get(area_col)
        t = row.get(time_col)
        v = row.get(value_col)
        if not area or not t or v in (None, ""):
            continue
        if area not in best or t > best[area][1]:
            try:
                best[area] = (round(float(v), 2), t)
            except ValueError:
                continue
    return best


# ── World Bank (reserva) ──────────────────────────────────────────────────────
# Um único pedido para TODOS os países de uma vez (em vez de um pedido por país,
# que era lento e podia demorar minutos com ~40 chamadas sequenciais).

def fetch_wb_bulk(wb_codes, indicator, attempts=2):
    """Devolve {wb_code: (valor, data)} para o indicador dado, num único pedido HTTP."""
    codes = ";".join(wb_codes)
    url = f"{WB_BASE}/{codes}/indicator/{indicator}?format=json&per_page=1000&mrnev=1"
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            result = {}
            if len(data) < 2 or not data[1]:
                return result
            for entry in data[1]:
                code = entry.get("country", {}).get("id") or entry.get("countryiso3code")
                val = entry.get("value")
                if val is None:
                    continue
                date_str = str(entry["date"])
                if code not in result or date_str > result[code][1]:
                    result[code] = (round(float(val), 2), date_str)
            return result
        except Exception as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(3)
    print(f"  [World Bank {indicator}] falhou: {last_err}")
    return {}


# ── Main ───────────────────────────────────────────────────────────────────────

def load_existing():
    """Carrega o hulbert_data.json actual do repo, para preservar os P/E."""
    if os.path.exists(REPO_JSON_PATH):
        try:
            with open(REPO_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Aviso: não consegui ler {REPO_JSON_PATH} existente: {e}")
    return {}


def main():
    print(f"Hulbert Macro Screen — fetch_macro.py — {TODAY}\n")
    existing = load_existing()

    print("A obter CPI da OECD (23 países-membros)...")
    oecd_cpi = get_oecd_cpi()
    print(f"  {len(oecd_cpi)} países com CPI da OECD\n")

    print("A obter Desemprego da OECD (23 países-membros)...")
    oecd_unemp = get_oecd_unemployment()
    print(f"  {len(oecd_unemp)} países com desemprego da OECD\n")

    all_wb_codes = [c["wb"] for c in COUNTRIES]
    print("A obter CPI do World Bank (todos os países, 1 pedido)...")
    wb_cpi = fetch_wb_bulk(all_wb_codes, "FP.CPI.TOTL.ZG")
    print(f"  {len(wb_cpi)} países com CPI do World Bank\n")

    print("A obter Desemprego do World Bank (todos os países, 1 pedido)...")
    wb_unemp = fetch_wb_bulk(all_wb_codes, "SL.UEM.TOTL.ZS")
    print(f"  {len(wb_unemp)} países com desemprego do World Bank\n")

    output = {
        "_updated": TODAY,
        "_sources": {
            "cpi": "OECD SDMX (mensal) para membros OECD; World Bank (anual) para os restantes",
            "unemployment": "OECD SDMX (mensal) para membros OECD; World Bank (anual) para os restantes",
            "pe": "Manual — preservado do ficheiro anterior",
            "note": "date shown per metric",
        },
    }

    for c in COUNTRIES:
        etf, wb_code, oecd_code = c["etf"], c["wb"], c["oecd"]
        print(f"→ {c['country']} ({etf})")

        # --- CPI ---
        cpi_val, cpi_date, cpi_src = None, None, None
        if oecd_code and oecd_code in oecd_cpi:
            cpi_val, cpi_date = oecd_cpi[oecd_code]
            cpi_src = "OECD"
        if cpi_val is None and wb_code in wb_cpi:
            cpi_val, cpi_date = wb_cpi[wb_code]
            cpi_src = "WorldBank"
        print(f"    CPI: {cpi_val} ({cpi_date}, {cpi_src})")

        # --- Unemployment ---
        unemp_val, unemp_date, unemp_src = None, None, None
        if oecd_code and oecd_code in oecd_unemp:
            unemp_val, unemp_date = oecd_unemp[oecd_code]
            unemp_src = "OECD"
        if unemp_val is None and wb_code in wb_unemp:
            unemp_val, unemp_date = wb_unemp[wb_code]
            unemp_src = "WorldBank"
        print(f"    Unemployment: {unemp_val} ({unemp_date}, {unemp_src})")

        # --- P/E: preservar o que já existe, nunca sobrescrever ---
        prev = existing.get(etf, {})
        pe_val = prev.get("pe")
        pe_date = prev.get("pe_date")

        output[etf] = {
            "country": c["country"],
            "region": c["region"],
            "cpi": cpi_val,
            "cpi_date": cpi_date,
            "cpi_source": cpi_src,
            "unemp": unemp_val,
            "unemp_date": unemp_date,
            "unemp_source": unemp_src,
            "pe": pe_val,
            "pe_date": pe_date,
        }

    with open(REPO_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✅ {REPO_JSON_PATH} actualizado com {len(COUNTRIES)} países.")


if __name__ == "__main__":
    main()
