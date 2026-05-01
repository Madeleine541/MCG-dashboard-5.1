from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# ============================================================
# 0. Page configuration
# ============================================================

st.set_page_config(
    page_title="SteelCBAM DPP Carbon Calculator",
    page_icon="🏭",
    layout="wide"
)

DEFAULT_FILE = "cbam_final_data.xlsx"

# Fallback country list used only if the selected Excel sheet has no country data.
FALLBACK_COUNTRIES = [
    "CHINA",
    "INDIA",
    "GERMANY",
    "US",
    "TURKEY",
    "SOUTH KOREA",
    "JAPAN",
    "VIETNAM",
    "UKRAINE",
    "RUSSIA",
    "FRANCE",
    "ITALY",
    "SPAIN",
    "NETHERLANDS",
    "BRAZIL",
]

# CBAM phase-in schedule from the dashboard specification document
CARBON_SCHEDULE = pd.DataFrame({
    "Year": [2025, 2026, 2027, 2028, 2029, 2030],
    "Carbon Price (£/tCO₂e)": [62, 68, 75, 83, 92, 100],
    "Phase-in Factor": [0.025, 0.10, 0.25, 0.50, 0.75, 1.00],
})

# Production route benchmarks from the dashboard specification document
ROUTE_BENCHMARKS = {
    "BF-BOF": 2.10,
    "EAF": 0.70,
    "EAF — Grid Mix": 0.70,
    "EAF — Renewable Energy": 0.30,
    "DRI-EAF (Hydrogen)": 0.15,
    "Unknown / No DPP": 2.50,
}

DEFAULT_FACTOR_NO_DPP = 2.50
SECTOR_AVERAGE_BFBOF = 2.10
BASELINE_SCENARIO_VOLUME = 2500


# ============================================================
# 1. Styling and helper functions
# ============================================================

def money(x):
    """Format number as GBP."""
    try:
        if pd.isna(x):
            return "£0"
        return f"£{x:,.0f}"
    except Exception:
        return "£0"


def pct(x):
    """Format number as percentage."""
    try:
        if pd.isna(x):
            return "0%"
        return f"{x:.1%}"
    except Exception:
        return "0%"


def safe_float(value, fallback):
    """Convert a value to float safely."""
    try:
        value = pd.to_numeric(value, errors="coerce")
        if pd.isna(value):
            return fallback
        return float(value)
    except Exception:
        return fallback


def get_sheet_case_insensitive(sheets, target_name):
    """Return a sheet by name without depending on exact capitalisation."""
    target = str(target_name).strip().lower()

    for name, df in sheets.items():
        if str(name).strip().lower() == target:
            return df

    return pd.DataFrame()


def normalize_percent_value(value):
    """Convert either 0.35 or 35 into 0.35."""
    value = safe_float(value, 0)
    if value > 1:
        return value / 100
    return value


def normalize_percent_series(series):
    """Convert percentage-like series to decimal form when needed."""
    s = pd.to_numeric(series, errors="coerce").fillna(0)
    if not s.empty and s.max() > 1:
        return s / 100
    return s


def is_yes(value):
    """Interpret yes/no fields from the workbook."""
    return str(value).strip().upper() in ["Y", "YES", "TRUE", "1"]


def get_countries_from_df(df, fallback=None):
    """
    Return sorted country list from a dataframe.
    This is used to keep CBAM and Simulated Data clearly separated.
    """
    if fallback is None:
        fallback = FALLBACK_COUNTRIES

    if df is not None and not df.empty and "Country" in df.columns:
        countries = (
            df["Country"]
            .dropna()
            .astype(str)
            .str.upper()
            .str.strip()
            .unique()
            .tolist()
        )
        countries = sorted([c for c in countries if c and c != "NAN"])
        if countries:
            return countries

    return sorted(fallback)


@st.cache_data(show_spinner=False)
def load_workbook(file_obj=None, fallback_path=DEFAULT_FILE):
    """
    Load all sheets from the Excel workbook.

    Priority:
    1. Uploaded file through Streamlit sidebar
    2. Local file in the same folder as this Python script
    """
    if file_obj is not None:
        xl = pd.ExcelFile(file_obj)
    else:
        path = Path(fallback_path)
        if not path.exists():
            st.error(
                f"Cannot find Excel file: {fallback_path}. "
                "Please ensure `cbam_final_data.xlsx` is placed in the same folder as `app.py`."
            )
            st.stop()
        xl = pd.ExcelFile(path)

    sheets = {}
    for name in xl.sheet_names:
        try:
            sheets[name] = pd.read_excel(xl, sheet_name=name)
        except Exception:
            sheets[name] = pd.DataFrame()

    return sheets


def clean_consignment(df):
    """
    Clean CBAM or Simulated Data sheet.

    Key fixes:
    - Keeps only real numeric consignment rows and removes NOTE/source rows.
    - Renames workbook columns into stable internal names.
    - Preserves CBAM fields that were previously cleaned but not exposed.
    """
    df = df.copy()
    df = df.dropna(how="all")

    if df.empty:
        return df

    if "No" in df.columns:
        no_numeric = pd.to_numeric(df["No"], errors="coerce")
        df = df[no_numeric.notna()].copy()

    rename = {
        "Project Date": "Project Date",
        "Consignment Reference": "Consignment Ref",
        "Country of Production": "Country",
        "Import Weight (Tonnes)": "Volume",
        "Actual Intensity (tCO₂e / t Steel)": "CO2 Intensity",
        "Weight of UK-sourced Precursor (t)": "UK Precursor",
        "Local Carbon Price Status": "Local Carbon Price Status",
        "Carbon Price Coverage Ratio (%)": "Coverage Ratio",
        "Consignment Value (GBP)": "Steel Value",
        "Embedded Emissions (tCO₂e)": "Embedded Emissions",
        "Adjusted Emissions (tCO₂e)": "Adjusted Emissions",
        "Current Effective CBAM Rate (GBP/tCO₂e)": "Effective CBAM Rate",
        "Total CBAM Charge (GBP)": "Total CBAM Charge",
        "Carbon Price Relief (CPR) (GBP)": "CPR",
        "Final CBAM Liability (GBP)": "Final CBAM Liability",
        "Mandatory Registration Requirement": "Mandatory Registration Requirement",
        "Potential Compliance Penalty (GBP)": "Potential Compliance Penalty",
        "DPP Implementation Cost (GBP)": "DPP Cost",
        "Net DPP Economic Benefit (GBP)": "Net DPP Benefit",
    }

    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    numeric_cols = [
        "Volume",
        "CO2 Intensity",
        "UK Precursor",
        "Coverage Ratio",
        "Steel Value",
        "Embedded Emissions",
        "Adjusted Emissions",
        "Effective CBAM Rate",
        "Total CBAM Charge",
        "CPR",
        "Final CBAM Liability",
        "Potential Compliance Penalty",
        "DPP Cost",
        "Net DPP Benefit",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "Coverage Ratio" in df.columns:
        df["Coverage Ratio"] = normalize_percent_series(df["Coverage Ratio"])

    if "Country" in df.columns:
        df["Country"] = df["Country"].astype(str).str.upper().str.strip()
        df = df[(df["Country"] != "") & (df["Country"] != "NAN")]

    if "Product" in df.columns:
        df["Product"] = df["Product"].astype(str).str.strip()

    if "Local Carbon Price Status" in df.columns:
        df["Local Carbon Price Status"] = (
            df["Local Carbon Price Status"]
            .astype(str)
            .str.upper()
            .str.strip()
        )

    if "Steel Value" in df.columns and "Volume" in df.columns:
        df["Price per Tonne"] = np.where(
            df["Volume"] > 0,
            df["Steel Value"] / df["Volume"],
            np.nan
        )

    if "Final CBAM Liability" in df.columns and "Steel Value" in df.columns:
        df["Total Cost"] = df["Steel Value"] + df["Final CBAM Liability"]

    return df


def clean_country_factors(df):
    """Clean country factors sheet and remove source-note rows."""
    df = df.copy()
    df = df.dropna(how="all")

    if df.empty:
        return df

    if "Country" in df.columns:
        df["Country"] = df["Country"].astype(str).str.upper().str.strip()
        df = df[
            (df["Country"] != "")
            & (df["Country"] != "NAN")
            & (df["Country"] != "SOURCES")
            & (~df["Country"].str.startswith("•", na=False))
        ].copy()

    for col in df.columns:
        if col != "Country" and "Source" not in str(col):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "BF-BOF Intensity (tCO₂e/t)" in df.columns:
        df = df[df["BF-BOF Intensity (tCO₂e/t)"].notna()].copy()

    return df


def get_param(sheets, term_contains, default=None):
    """
    Read a parameter from the 'basic parameter' sheet.
    """
    df = get_sheet_case_insensitive(sheets, "basic parameter")

    if df.empty:
        return default

    if "Professional Term" not in df.columns or "amount" not in df.columns:
        return default

    hit = df[
        df["Professional Term"]
        .astype(str)
        .str.contains(term_contains, case=False, regex=False, na=False)
    ]

    if hit.empty:
        return default

    val = pd.to_numeric(hit.iloc[0]["amount"], errors="coerce")

    if pd.isna(val):
        return default

    return float(val)


def aggregate_supplier_route(df):
    """
    Aggregate shipment-level data by country and production route.

    Avg_Intensity is now volume-weighted, using Embedded Emissions / Volume.
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    required = [
        "Country",
        "Product",
        "Volume",
        "Embedded Emissions",
        "Adjusted Emissions",
        "Steel Value",
        "Total CBAM Charge",
        "CPR",
        "Final CBAM Liability",
        "Potential Compliance Penalty",
        "DPP Cost",
        "Net DPP Benefit",
    ]

    for col in required:
        if col not in df.columns:
            df[col] = 0

    if "Consignment Ref" not in df.columns:
        df["Consignment Ref"] = range(len(df))

    g = df.groupby(["Country", "Product"], dropna=False).agg(
        Volume=("Volume", "sum"),
        Shipments=("Consignment Ref", "count"),
        Embedded=("Embedded Emissions", "sum"),
        Adjusted=("Adjusted Emissions", "sum"),
        Steel_Value=("Steel Value", "sum"),
        Total_Charge=("Total CBAM Charge", "sum"),
        CPR=("CPR", "sum"),
        CBAM=("Final CBAM Liability", "sum"),
        Penalty=("Potential Compliance Penalty", "sum"),
        DPP_Cost=("DPP Cost", "sum"),
        DPP_Benefit=("Net DPP Benefit", "sum"),
    ).reset_index()

    g["Avg_Intensity"] = np.where(
        g["Volume"] > 0,
        g["Embedded"] / g["Volume"],
        0
    )

    g["Price_per_t"] = np.where(
        g["Volume"] > 0,
        g["Steel_Value"] / g["Volume"],
        0
    )

    g["TCO"] = g["Steel_Value"] + g["CBAM"]

    g["CBAM_per_t"] = np.where(
        g["Volume"] > 0,
        g["CBAM"] / g["Volume"],
        0
    )

    return g.sort_values("CBAM", ascending=False)


def aggregate_country(df, selected_countries):
    """
    Aggregate consignment data to country level.

    Avg_Intensity is now volume-weighted, using Embedded Emissions / Volume.
    """
    selected_countries = list(selected_countries)

    if df.empty or not selected_countries:
        return pd.DataFrame()

    d = df[df["Country"].isin(selected_countries)].copy()

    if d.empty:
        return pd.DataFrame()

    required = [
        "Country",
        "Volume",
        "Embedded Emissions",
        "Adjusted Emissions",
        "Steel Value",
        "Total CBAM Charge",
        "CPR",
        "Final CBAM Liability",
        "Potential Compliance Penalty",
        "DPP Cost",
        "Net DPP Benefit",
    ]

    for col in required:
        if col not in d.columns:
            d[col] = 0

    if "Consignment Ref" not in d.columns:
        d["Consignment Ref"] = range(len(d))

    g = d.groupby("Country", dropna=False).agg(
        Volume=("Volume", "sum"),
        Shipments=("Consignment Ref", "count"),
        Embedded=("Embedded Emissions", "sum"),
        Adjusted=("Adjusted Emissions", "sum"),
        Steel_Value=("Steel Value", "sum"),
        Total_Charge=("Total CBAM Charge", "sum"),
        CPR=("CPR", "sum"),
        CBAM=("Final CBAM Liability", "sum"),
        Penalty=("Potential Compliance Penalty", "sum"),
        DPP_Cost=("DPP Cost", "sum"),
        DPP_Benefit=("Net DPP Benefit", "sum"),
    ).reset_index()

    numeric_cols = [
        "Volume",
        "Shipments",
        "Embedded",
        "Adjusted",
        "Steel_Value",
        "Total_Charge",
        "CPR",
        "CBAM",
        "Penalty",
        "DPP_Cost",
        "DPP_Benefit",
    ]

    for col in numeric_cols:
        g[col] = pd.to_numeric(g[col], errors="coerce").fillna(0)

    g["Avg_Intensity"] = np.where(
        g["Volume"] > 0,
        g["Embedded"] / g["Volume"],
        0
    )

    g["TCO"] = g["Steel_Value"] + g["CBAM"]

    g["CBAM_per_t"] = np.where(
        g["Volume"] > 0,
        g["CBAM"] / g["Volume"],
        0
    )

    return g.sort_values("CBAM", ascending=False)


def forecast_liability(
    intensity,
    volume,
    no_dpp=False,
    uk_precursor=0,
    coverage_ratio=0,
    local_carbon_price_status="N",
    export_carbon_price=0,
    fx_rate=1.0,
    precursor_factor=0,
    fa_factor=1.0,
    include_fa_adjustment=False,
):
    """
    Forecast CBAM liability from 2025 to 2030.

    The default behaviour remains comparable with the previous simplified model:
    CBAM Liability = CO2 intensity × volume × carbon price × phase-in factor.

    Extra optional inputs allow the forecast to reflect adjusted emissions,
    local carbon price relief and DPP default-factor risk when those data are available.
    """
    factor = DEFAULT_FACTOR_NO_DPP if no_dpp else intensity
    factor = safe_float(factor, DEFAULT_FACTOR_NO_DPP)
    volume = safe_float(volume, 0)
    uk_precursor = safe_float(uk_precursor, 0)
    coverage_ratio = normalize_percent_value(coverage_ratio)
    export_carbon_price = safe_float(export_carbon_price, 0)
    fx_rate = safe_float(fx_rate, 1)
    precursor_factor = safe_float(precursor_factor, 0)
    fa_factor = safe_float(fa_factor, 1)

    embedded = factor * volume
    adjusted = max(embedded - uk_precursor * precursor_factor, 0)

    out = CARBON_SCHEDULE.copy()
    out["Embedded Emissions"] = embedded
    out["Adjusted Emissions"] = adjusted
    out["Effective Forecast Rate"] = (
        out["Carbon Price (£/tCO₂e)"]
        * out["Phase-in Factor"]
    )

    if include_fa_adjustment:
        out["Effective Forecast Rate"] = out["Effective Forecast Rate"] * fa_factor

    out["Gross CBAM Charge"] = adjusted * out["Effective Forecast Rate"]

    if is_yes(local_carbon_price_status):
        out["Carbon Price Relief"] = (
            adjusted
            * coverage_ratio
            * export_carbon_price
            * fx_rate
            * out["Phase-in Factor"]
        )
    else:
        out["Carbon Price Relief"] = 0

    out["CBAM Liability"] = np.maximum(
        out["Gross CBAM Charge"] - out["Carbon Price Relief"],
        0
    )

    numeric_cols = [
        "CBAM Liability",
        "Embedded Emissions",
        "Adjusted Emissions",
        "Effective Forecast Rate",
        "Gross CBAM Charge",
        "Carbon Price Relief",
    ]

    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    return out


def dpp_completeness(row):
    """
    Composite DPP completeness score.

    Scoring logic:
    - 40 points: DPP availability
    - 30 points: verified certification
    - 15 points: CO2 data present
    - 15 points: recycled content declared
    """
    score = 0

    score += 40 if row.get("DPP Available", True) else 0

    cert = row.get("Certification", "Verified")

    if cert in ["Verified", "EN 10204 3.1", "EN 10204 3.2"]:
        score += 30
    elif cert == "Self-declared":
        score += 10

    intensity = safe_float(row.get("CO2 Intensity", 0), 0)
    recycled = safe_float(row.get("Recycled Content", 0), 0)

    score += 15 if intensity > 0 else 0
    score += min(15, max(0, recycled) / 100 * 15)

    return min(score, 100)


def esg_score(intensity, recycled_pct, dpp_available, certification):
    """
    ESG score:
    - Carbon intensity: 30 points
    - Recycled content: 25 points
    - DPP availability: 25 points
    - Certification level: 20 points
    """
    intensity = safe_float(intensity, DEFAULT_FACTOR_NO_DPP)
    recycled_pct = safe_float(recycled_pct, 0)

    carbon_points = max(
        0,
        min(30, (2.5 - intensity) / (2.5 - 0.1) * 30)
    )

    recycled_points = max(
        0,
        min(25, recycled_pct / 83 * 25)
    )

    dpp_points = 25 if dpp_available else 0

    if certification in ["Verified", "EN 10204 3.1", "EN 10204 3.2"]:
        cert_points = 20
    elif certification == "Self-declared":
        cert_points = 10
    else:
        cert_points = 0

    return carbon_points + recycled_points + dpp_points + cert_points


def recommendation(score, intensity, dpp_available):
    """
    Procurement recommendation.
    """
    score = safe_float(score, 0)
    intensity = safe_float(intensity, DEFAULT_FACTOR_NO_DPP)

    if score >= 70 and intensity <= 1.5 and dpp_available:
        return "Best ESG"
    elif score >= 45:
        return "Consider"
    else:
        return "Avoid"


def get_country_factor_row(country_factors, country):
    """Return the matching country factor row, or None if unavailable."""
    if country_factors.empty or "Country" not in country_factors.columns:
        return None

    matched = country_factors[country_factors["Country"] == country]

    if matched.empty:
        return None

    return matched.iloc[0]


def sidebar_supplier_inputs(country_factors, country_list, key_prefix="supplier"):
    """
    Editable supplier cards in sidebar.

    It displays countries from the currently selected data source only:
    - CBAM mode: countries in the CBAM sheet
    - Simulated Data mode: countries in the Simulated Data sheet

    This keeps case-level and simulated portfolio data clearly separated.
    """
    st.sidebar.subheader("Supplier comparison inputs")

    suppliers = []
    countries = list(country_list)

    st.sidebar.caption(
        f"Showing {len(countries)} countries from the selected data source."
    )

    for i, country in enumerate(countries):
        with st.sidebar.expander(f"Supplier {i + 1} — {country}", expanded=False):
            row = get_country_factor_row(country_factors, country)

            if row is None:
                st.caption("No country-factor data available. Default factor is used.")

            route = st.selectbox(
                "Production route",
                [
                    "BF-BOF",
                    "EAF",
                    "EAF — Renewable Energy",
                    "DRI-EAF (Hydrogen)",
                    "Unknown / No DPP"
                ],
                key=f"{key_prefix}_route_{i}"
            )

            default_intensity = DEFAULT_FACTOR_NO_DPP

            if row is not None:
                if route == "BF-BOF":
                    default_intensity = safe_float(
                        row.get("BF-BOF Intensity (tCO₂e/t)", 2.1),
                        2.1
                    )
                elif route == "EAF":
                    default_intensity = safe_float(
                        row.get("EAF Intensity (tCO₂e/t)", 0.7),
                        0.7
                    )
                elif route == "Unknown / No DPP":
                    default_intensity = DEFAULT_FACTOR_NO_DPP
                else:
                    default_intensity = ROUTE_BENCHMARKS.get(route, 0.7)

            route_key = (
                str(route)
                .replace(" ", "_")
                .replace("/", "_")
                .replace("—", "-")
                .replace("(", "")
                .replace(")", "")
            )

            intensity = st.number_input(
                "CO₂ intensity (tCO₂e/t)",
                min_value=0.0,
                value=float(default_intensity),
                step=0.05,
                key=f"{key_prefix}_intensity_{i}_{route_key}"
            )

            price = st.number_input(
                "Price per tonne (£)",
                min_value=0.0,
                value=900.0 + i * 20,
                step=10.0,
                key=f"{key_prefix}_price_{i}"
            )

            recycled = st.slider(
                "Recycled content (%)",
                0,
                100,
                min(20 + i * 3, 100),
                key=f"{key_prefix}_recycled_{i}"
            )

            dpp = st.checkbox(
                "DPP available",
                value=True,
                key=f"{key_prefix}_dpp_{i}"
            )

            cert = st.selectbox(
                "Certification level",
                ["Verified", "Self-declared", "Unknown"],
                key=f"{key_prefix}_cert_{i}"
            )

            suppliers.append({
                "Supplier": country,
                "Country": country,
                "Route": route,
                "CO2 Intensity": safe_float(intensity, DEFAULT_FACTOR_NO_DPP),
                "Price per Tonne": safe_float(price, 900),
                "Recycled Content": safe_float(recycled, 0),
                "DPP Available": dpp,
                "Certification": cert,
                "Country Factor Status": "Data available" if row is not None else "No country-factor data",
            })

    supplier_df = pd.DataFrame(suppliers)

    if not supplier_df.empty:
        supplier_df["CO2 Intensity"] = pd.to_numeric(
            supplier_df["CO2 Intensity"],
            errors="coerce"
        ).fillna(DEFAULT_FACTOR_NO_DPP)

        supplier_df["Price per Tonne"] = pd.to_numeric(
            supplier_df["Price per Tonne"],
            errors="coerce"
        ).fillna(900)

        supplier_df["Recycled Content"] = pd.to_numeric(
            supplier_df["Recycled Content"],
            errors="coerce"
        ).fillna(0)

    return supplier_df


def supplier_forecast_table(supplier_df, annual_volume):
    """Build a 2025–2030 forecast table for selected data-source suppliers."""
    forecast_rows = []

    for _, s in supplier_df.iterrows():
        use_default_factor = (
            not bool(s.get("DPP Available", True))
            or str(s.get("Certification", "Verified")) == "Unknown"
            or str(s.get("Route", "")) == "Unknown / No DPP"
        )

        f = forecast_liability(
            s["CO2 Intensity"],
            annual_volume,
            no_dpp=use_default_factor,
        )

        f["Supplier"] = s["Supplier"]
        f["Country Factor Status"] = s.get("Country Factor Status", "Data available")
        f["DPP Applied"] = not use_default_factor
        f["Forecast Intensity Used"] = (
            DEFAULT_FACTOR_NO_DPP if use_default_factor else s["CO2 Intensity"]
        )
        f["Total Cost"] = (
            safe_float(s["Price per Tonne"], 900) * annual_volume
            + f["CBAM Liability"]
        )
        forecast_rows.append(f)

    if not forecast_rows:
        return pd.DataFrame()

    forecast = pd.concat(forecast_rows, ignore_index=True)

    for col in ["CBAM Liability", "Total Cost", "Forecast Intensity Used"]:
        forecast[col] = pd.to_numeric(
            forecast[col],
            errors="coerce"
        ).fillna(0)

    return forecast


def build_dpp_risk_table(supplier_df, annual_volume):
    """Build DPP risk premium table for supplier comparison."""
    rows = []

    for _, s in supplier_df.iterrows():
        verified = (
            forecast_liability(s["CO2 Intensity"], annual_volume)
            .query("Year == 2030")["CBAM Liability"]
            .iloc[0]
        )

        no_dpp = (
            forecast_liability(s["CO2 Intensity"], annual_volume, no_dpp=True)
            .query("Year == 2030")["CBAM Liability"]
            .iloc[0]
        )

        risk_premium = max(no_dpp - verified, 0)
        comp = dpp_completeness(s)

        rows.append({
            **s.to_dict(),
            "DPP Completeness": comp,
            "2030 Liability with DPP": verified,
            "2030 Liability without DPP": no_dpp,
            "Default Factor Risk Premium": risk_premium,
        })

    out = pd.DataFrame(rows)

    if not out.empty:
        numeric_cols = [
            "CO2 Intensity",
            "DPP Completeness",
            "2030 Liability with DPP",
            "2030 Liability without DPP",
            "Default Factor Risk Premium",
        ]
        for col in numeric_cols:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    return out


def build_supplier_scenario_table(supplier_df, annual_volume, scenario_year):
    """
    Build a supplier-level scenario table from sidebar inputs.

    This is used when the user expects editable sidebar assumptions
    such as route, CO2 intensity, price, DPP status, certification and
    recycled content to directly affect charts.
    """
    if supplier_df.empty:
        return pd.DataFrame()

    d = supplier_df.copy()
    annual_volume = safe_float(annual_volume, 0)

    scenario_row = CARBON_SCHEDULE[
        CARBON_SCHEDULE["Year"] == scenario_year
    ].iloc[0]

    d["Use Default Factor"] = (
        (~d["DPP Available"].astype(bool))
        | (d["Certification"].astype(str) == "Unknown")
        | (d["Route"].astype(str) == "Unknown / No DPP")
    )

    d["Effective Intensity for CBAM"] = np.where(
        d["Use Default Factor"],
        DEFAULT_FACTOR_NO_DPP,
        d["CO2 Intensity"]
    )

    d["Scenario Year"] = scenario_year
    d["Annual Volume"] = annual_volume
    d["Scenario_CBAM"] = (
        d["Effective Intensity for CBAM"]
        * annual_volume
        * scenario_row["Carbon Price (£/tCO₂e)"]
        * scenario_row["Phase-in Factor"]
    )
    d["Baseline_CBAM_2500t"] = (
        d["Effective Intensity for CBAM"]
        * BASELINE_SCENARIO_VOLUME
        * scenario_row["Carbon Price (£/tCO₂e)"]
        * scenario_row["Phase-in Factor"]
    )
    d["Volume_Impact_vs_Baseline"] = (
        d["Scenario_CBAM"] - d["Baseline_CBAM_2500t"]
    )
    d["Scenario_Total_Cost"] = (
        d["Price per Tonne"] * annual_volume + d["Scenario_CBAM"]
    )
    d["Scenario_CBAM_per_t"] = np.where(
        annual_volume > 0,
        d["Scenario_CBAM"] / annual_volume,
        0
    )
    d["DPP Completeness"] = d.apply(dpp_completeness, axis=1)
    d["ESG Score"] = d.apply(
        lambda r: esg_score(
            r["CO2 Intensity"],
            r["Recycled Content"],
            r["DPP Available"],
            r["Certification"],
        ),
        axis=1
    )

    numeric_cols = [
        "CO2 Intensity",
        "Effective Intensity for CBAM",
        "Price per Tonne",
        "Recycled Content",
        "Scenario_CBAM",
        "Baseline_CBAM_2500t",
        "Volume_Impact_vs_Baseline",
        "Scenario_Total_Cost",
        "Scenario_CBAM_per_t",
        "DPP Completeness",
        "ESG Score",
    ]

    for col in numeric_cols:
        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0)

    return d


# ============================================================
# 2. Load workbook
# ============================================================

st.sidebar.caption("Workbook source: `cbam_final_data.xlsx` included in this GitHub repository.")

sheets = load_workbook(file_obj=None, fallback_path=DEFAULT_FILE)

cbam = clean_consignment(get_sheet_case_insensitive(sheets, "CBAM"))
simulated = clean_consignment(get_sheet_case_insensitive(sheets, "Simulated Data"))
country_factors = clean_country_factors(get_sheet_case_insensitive(sheets, "country factors"))

uk_ets_price = get_param(sheets, "UK ETS Average Price", 49.41)
fa_factor = get_param(sheets, "Free Allocation Adjustment Factor", 0.76605)
effective_rate = uk_ets_price * fa_factor


# ============================================================
# 3. Sidebar global controls
# ============================================================

st.sidebar.title("SteelCBAM Dashboard")

data_choice = st.sidebar.radio(
    "Data source",
    ["CBAM", "Simulated Data"],
    horizontal=True
)

base_df = cbam if data_choice == "CBAM" else simulated
current_countries = get_countries_from_df(base_df)

role = st.sidebar.radio(
    "Role selector",
    ["Importer", "Manufacturer", "Buyer / Trader"],
    horizontal=False
)

# Role-specific scenario controls are defined inside each role view.


# ============================================================
# 4. Header
# ============================================================

st.title("SteelCBAM — Digital Product Passport Carbon Calculator")

st.caption(
    "A multi-stakeholder CBAM and DPP decision-support dashboard "
    "built from the new Excel workbook."
)

with st.expander("Workbook and model parameters", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Loaded data source", data_choice)
    c2.metric("UK ETS price", money(uk_ets_price) + "/tCO₂e")
    c3.metric("FA adjustment", f"{fa_factor:.5f}")
    c4.metric("Effective CBAM rate", money(effective_rate) + "/tCO₂e")

if data_choice == "CBAM":
    st.info(
        "Current dataset: **CBAM** — a smaller case-level consignment dataset "
        "used to demonstrate direct CBAM liability calculations."
    )
else:
    st.info(
        "Current dataset: **Simulated Data** — a larger portfolio-level dataset "
        "used to test CBAM exposure across a wider set of consignments."
    )


# Data coverage note
with st.expander("Data coverage note", expanded=False):
    cbam_countries = get_countries_from_df(cbam, fallback=[])
    simulated_countries = get_countries_from_df(simulated, fallback=[])

    coverage = pd.DataFrame({
        "Country": sorted(set(cbam_countries) | set(simulated_countries)),
    })

    coverage["In CBAM"] = coverage["Country"].isin(cbam_countries)
    coverage["In Simulated Data"] = coverage["Country"].isin(simulated_countries)

    factor_countries = get_countries_from_df(country_factors, fallback=[])
    coverage["Country Factor Available"] = coverage["Country"].isin(factor_countries)

    st.write(
        "The workbook contains two main consignment-level datasets. "
        "They are not forced into one combined view because mixing case-level "
        "records and simulated records makes CBAM exposure harder to interpret."
    )

    st.dataframe(coverage, use_container_width=True)


# ============================================================
# 5. Importer View
# ============================================================

def render_importer_view():

    st.header("Importer view — CBAM liability and supplier switching")

    st.write(
        "This view helps UK importers compare CBAM liability, "
        "forecast exposure from 2025 to 2030, and assess DPP risk."
    )

    st.sidebar.subheader("Importer scenario inputs")

    annual_volume = st.sidebar.number_input(
        "Annual volume (tonnes)",
        min_value=1,
        value=2500,
        step=100,
        key="importer_annual_volume"
    )

    budget = st.sidebar.number_input(
        "Budget / premium allowance (£)",
        min_value=0,
        value=75000,
        step=5000,
        key="importer_budget"
    )

    importer_supplier_df = sidebar_supplier_inputs(
        country_factors,
        current_countries,
        key_prefix=f"importer_{data_choice.replace(' ', '_').lower()}"
    )

    tab1, tab2, tab3 = st.tabs(
        ["Cost Calculator", "CBAM Forecast", "DPP Compliance"]
    )

    with tab1:
        st.caption(
            "This tab shows countries from the currently selected data source only. "
            "Switch the Data source control to compare the CBAM case dataset with "
            "the simulated portfolio dataset. The cost calculator uses workbook "
            "consignment records; the forecast and DPP modules use editable scenario "
            "inputs in the sidebar."
        )

        countries = st.multiselect(
            "Filter countries",
            current_countries,
            default=current_countries
        )

        if not countries:
            st.warning("Please select at least one country.")
        else:
            country_agg = aggregate_country(base_df, countries)

            if country_agg.empty:
                st.warning(
                    "No data available for the selected countries in this data source."
                )
            else:
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Countries in current dataset", len(current_countries))
                k2.metric("Countries selected", len(countries))
                k3.metric("Total shipments", int(country_agg["Shipments"].sum()))
                k4.metric("Total CBAM liability", money(country_agg["CBAM"].sum()))

                left, right = st.columns([1.25, 1])

                with left:
                    st.subheader("Supplier ranking by country-level CBAM liability")
                    show_cols = [
                        "Country",
                        "Shipments",
                        "Volume",
                        "Avg_Intensity",
                        "Embedded",
                        "Adjusted",
                        "Total_Charge",
                        "CPR",
                        "CBAM",
                        "CBAM_per_t",
                        "Penalty",
                        "TCO",
                        "DPP_Benefit",
                    ]
                    show_cols = [c for c in show_cols if c in country_agg.columns]
                    st.dataframe(country_agg[show_cols], use_container_width=True)

                with right:
                    fig = px.bar(
                        country_agg,
                        x="Country",
                        y="CBAM",
                        title=f"Country-level CBAM liability — {data_choice}"
                    )
                    st.plotly_chart(fig, use_container_width=True)

                route_detail = aggregate_supplier_route(
                    base_df[base_df["Country"].isin(countries)]
                )

                with st.expander("Route-level detail for selected countries"):
                    if route_detail.empty:
                        st.info("No route-level data available for the selected countries.")
                    else:
                        st.dataframe(route_detail, use_container_width=True)

                if "supplier_scenario" in locals() and not supplier_scenario.empty:
                    cleanest = supplier_scenario.sort_values(
                        "Effective Intensity for CBAM"
                    ).iloc[0]
                    dirtiest = supplier_scenario.sort_values(
                        "Effective Intensity for CBAM",
                        ascending=False
                    ).iloc[0]

                    saving_5y = 0

                    for _, row in CARBON_SCHEDULE.iterrows():
                        saving_5y += (
                            (
                                dirtiest["Effective Intensity for CBAM"]
                                - cleanest["Effective Intensity for CBAM"]
                            )
                            * annual_volume
                            * row["Carbon Price (£/tCO₂e)"]
                            * row["Phase-in Factor"]
                        )

                    verdict = (
                        "Switch supplier"
                        if saving_5y > budget
                        else "Review assumptions / keep monitoring"
                    )

                    st.info(
                        f"Pay-vs-switch verdict: **{verdict}**. "
                        f"Estimated 2025–2030 CBAM saving is **{money(saving_5y)}**, "
                        f"compared with budget/premium allowance of **{money(budget)}**. "
                        f"Comparison uses editable supplier inputs: cleanest = "
                        f"**{cleanest['Supplier']}**, highest-risk = **{dirtiest['Supplier']}**."
                    )
                else:
                    st.info("Pay-vs-switch verdict is unavailable because no supplier scenario rows are selected.")

    with tab2:
        forecast = supplier_forecast_table(importer_supplier_df, annual_volume)

        st.subheader(f"CBAM forecast, 2025–2030 — {data_choice}")

        if forecast.empty:
            st.warning("No supplier forecast data available.")
        else:
            forecast_metric = st.radio(
                "Forecast chart metric",
                ["CBAM Liability", "Total Cost"],
                index=0,
                horizontal=True,
                key=f"importer_forecast_metric_{data_choice.replace(' ', '_').lower()}"
            )

            c1, c2 = st.columns([1.2, 1])

            with c1:
                fig = px.line(
                    forecast,
                    x="Year",
                    y=forecast_metric,
                    color="Supplier",
                    markers=True,
                    title=f"Projected {forecast_metric.lower()} by supplier"
                )
                st.plotly_chart(fig, use_container_width=True)

            with c2:
                cumulative = (
                    forecast
                    .groupby("Supplier", as_index=False)[forecast_metric]
                    .sum()
                    .sort_values(forecast_metric)
                )

                fig2 = px.bar(
                    cumulative,
                    x="Supplier",
                    y=forecast_metric,
                    title=f"Cumulative 2025–2030 {forecast_metric.lower()}"
                )
                st.plotly_chart(fig2, use_container_width=True)

            st.dataframe(
                forecast.pivot_table(
                    index="Year",
                    columns="Supplier",
                    values=forecast_metric,
                    aggfunc="sum"
                ),
                use_container_width=True
            )

    with tab3:
        dpp_df = build_dpp_risk_table(importer_supplier_df, annual_volume)

        if dpp_df.empty:
            st.warning("No DPP risk data available.")
        else:
            k1, k2, k3 = st.columns(3)
            k1.metric("Avg DPP completeness", f"{dpp_df['DPP Completeness'].mean():.1f}%")
            k2.metric("Highest default-factor risk", money(dpp_df["Default Factor Risk Premium"].max()))
            k3.metric("Suppliers without DPP", int((~dpp_df["DPP Available"]).sum()))

            st.dataframe(
                dpp_df[
                    [
                        "Supplier",
                        "Country",
                        "Country Factor Status",
                        "Route",
                        "CO2 Intensity",
                        "DPP Available",
                        "Certification",
                        "DPP Completeness",
                        "2030 Liability with DPP",
                        "2030 Liability without DPP",
                        "Default Factor Risk Premium",
                    ]
                ],
                use_container_width=True
            )

            dpp_chart_mode = st.radio(
                "DPP chart metric",
                [
                    "Liability with vs without DPP",
                    "Default factor risk premium",
                    "DPP completeness"
                ],
                horizontal=True,
                key=f"importer_dpp_chart_metric_{data_choice.replace(' ', '_').lower()}"
            )

            if dpp_chart_mode == "Liability with vs without DPP":
                fig = px.bar(
                    dpp_df,
                    x="Supplier",
                    y=["2030 Liability with DPP", "2030 Liability without DPP"],
                    barmode="group",
                    title="Financial value of verified DPP data"
                )
            elif dpp_chart_mode == "Default factor risk premium":
                fig = px.bar(
                    dpp_df,
                    x="Supplier",
                    y="Default Factor Risk Premium",
                    color="DPP Available",
                    title="Default factor risk premium by supplier"
                )
            else:
                fig = px.bar(
                    dpp_df,
                    x="Supplier",
                    y="DPP Completeness",
                    color="Certification",
                    title="DPP completeness by supplier"
                )

            st.plotly_chart(fig, use_container_width=True)


# ============================================================
# 6. Manufacturer View
# ============================================================

def render_manufacturer_view():

    st.header("Manufacturer view — emissions, DPP issuance, and buyer competitiveness")

    st.write(
        "This view reframes CBAM as a supplier competitiveness issue. "
        "Lower declared emissions reduce buyers’ CBAM burden."
    )

    tab1, tab2, tab3 = st.tabs(
        ["Emissions Tracker", "DPP Issuance", "Carbon Price Impact"]
    )

    with st.sidebar.expander("Manufacturer production inputs", expanded=True):
        route = st.selectbox(
            "Primary production route",
            list(ROUTE_BENCHMARKS.keys()),
            index=0,
            key="manufacturer_route"
        )

        scope1 = st.number_input(
            "Scope 1 intensity (tCO₂e/t)",
            min_value=0.0,
            value=1.80,
            step=0.05,
            key="manufacturer_scope1"
        )

        scope2 = st.number_input(
            "Scope 2 intensity (tCO₂e/t)",
            min_value=0.0,
            value=0.45,
            step=0.05,
            key="manufacturer_scope2"
        )

        recycled_pct = st.slider(
            "Recycled scrap input (%)",
            0,
            100,
            30,
            key="manufacturer_recycled"
        )

        dpp_rate = st.slider(
            "DPP issuance rate (%)",
            0,
            100,
            75,
            key="manufacturer_dpp_rate"
        )

        cert_rate = st.slider(
            "Verified certificate attachment rate (%)",
            0,
            100,
            65,
            key="manufacturer_cert_rate"
        )

        production_volume = st.number_input(
            "Annual production/output volume (tonnes)",
            min_value=1,
            value=2500,
            step=100,
            key="manufacturer_output_volume"
        )

    total_intensity = scope1 + scope2
    route_benchmark_intensity = ROUTE_BENCHMARKS.get(route, SECTOR_AVERAGE_BFBOF)

    buyer_2025 = total_intensity * production_volume * 62 * 0.025
    buyer_2030 = total_intensity * production_volume * 100 * 1.0

    gap_tonnes = production_volume * (1 - dpp_rate / 100)
    dpp_gap_risk = max(
        0,
        (DEFAULT_FACTOR_NO_DPP - total_intensity)
        * gap_tonnes
        * 100
    )

    with tab1:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Scope 1+2 intensity", f"{total_intensity:.2f} tCO₂e/t")
        k2.metric(
            "vs BF-BOF sector avg",
            f"{(total_intensity / SECTOR_AVERAGE_BFBOF - 1) * 100:.1f}%"
        )
        k3.metric("Buyer CBAM 2025", money(buyer_2025))
        k4.metric("Buyer CBAM 2030", money(buyer_2030))

        comp = pd.DataFrame({
            "Source": ["Scope 1", "Scope 2"],
            "Intensity": [scope1, scope2]
        })

        c1, c2 = st.columns(2)

        with c1:
            fig = px.bar(
                comp,
                x="Source",
                y="Intensity",
                title="Scope 1 + Scope 2 intensity breakdown"
            )
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            bench = pd.DataFrame({
                "Route": list(ROUTE_BENCHMARKS.keys()) + ["Your steel"],
                "Intensity": list(ROUTE_BENCHMARKS.values()) + [total_intensity]
            })

            fig2 = px.bar(
                bench,
                x="Route",
                y="Intensity",
                title="Intensity vs route benchmarks"
            )
            st.plotly_chart(fig2, use_container_width=True)

    with tab2:
        completeness = min(
            100,
            dpp_rate * 0.40
            + cert_rate * 0.30
            + 15
            + min(15, recycled_pct / 100 * 15)
        )

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("DPPs issued", f"{dpp_rate}%")
        k2.metric("Verified cert rate", f"{cert_rate}%")
        k3.metric("Avg completeness", f"{completeness:.1f}%")
        k4.metric("DPP gap risk", money(dpp_gap_risk))

        targets = pd.DataFrame({
            "Metric": [
                "DPP coverage",
                "Verified certificate",
                "CO₂ data completeness",
                "Passport completeness",
                "SVHC declaration",
            ],
            "Current": [dpp_rate, cert_rate, 100, completeness, 70],
            "Target": [95, 100, 100, 95, 100],
        })

        targets["Gap"] = targets["Target"] - targets["Current"]
        targets["Priority"] = np.where(
            targets["Gap"] >= 20,
            "High",
            np.where(targets["Gap"] > 0, "Medium", "On target")
        )

        st.dataframe(targets, use_container_width=True)

        fig = px.bar(
            targets,
            x="Metric",
            y=["Current", "Target"],
            barmode="group",
            title="DPP issuance target vs current state"
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.caption(
            "This tab is driven by the Manufacturer production inputs: "
            "Scope 1, Scope 2, selected route and production volume."
        )

        f = forecast_liability(total_intensity, production_volume)

        f["Your steel liability"] = f["CBAM Liability"]

        f["Sector average liability"] = (
            SECTOR_AVERAGE_BFBOF
            * production_volume
            * f["Carbon Price (£/tCO₂e)"]
            * f["Phase-in Factor"]
        )

        f["Selected route benchmark liability"] = (
            route_benchmark_intensity
            * production_volume
            * f["Carbon Price (£/tCO₂e)"]
            * f["Phase-in Factor"]
        )

        f["Buyer saving vs sector average"] = (
            f["Sector average liability"]
            - f["Your steel liability"]
        )

        fig = px.line(
            f,
            x="Year",
            y=[
                "Your steel liability",
                "Sector average liability",
                "Selected route benchmark liability"
            ],
            markers=True,
            title=(
                f"Buyer CBAM burden: your steel vs sector average vs selected route "
                f"({route})"
            )
        )
        fig.update_layout(yaxis_title="CBAM liability (£)")

        st.plotly_chart(fig, use_container_width=True)

        selected_2030 = f.loc[f["Year"] == 2030, "Your steel liability"].iloc[0]
        route_2030 = f.loc[f["Year"] == 2030, "Selected route benchmark liability"].iloc[0]

        m1, m2, m3 = st.columns(3)
        m1.metric("Production volume", f"{production_volume:,.0f} t")
        m2.metric("2030 liability: your steel", money(selected_2030))
        m3.metric(f"2030 route benchmark: {route}", money(route_2030))

        st.dataframe(
            f[
                [
                    "Year",
                    "Carbon Price (£/tCO₂e)",
                    "Phase-in Factor",
                    "Your steel liability",
                    "Sector average liability",
                    "Selected route benchmark liability",
                    "Buyer saving vs sector average",
                ]
            ],
            use_container_width=True
        )


# ============================================================
# 7. Buyer / Trader View
# ============================================================

def render_buyer_trader_view():

    st.header("Buyer / Trader view — ESG scoring and procurement comparison")

    st.write(
        "This view combines cost, carbon, DPP status, certification, "
        "and ESG score into a procurement recommendation."
    )

    st.sidebar.subheader("Buyer / Trader scenario inputs")

    annual_volume = st.sidebar.number_input(
        "Annual volume (tonnes)",
        min_value=1,
        value=2500,
        step=100,
        key="buyer_annual_volume"
    )

    budget = st.sidebar.number_input(
        "Budget / premium allowance (£)",
        min_value=0,
        value=75000,
        step=5000,
        key="buyer_budget"
    )

    buyer_supplier_df = sidebar_supplier_inputs(
        country_factors,
        current_countries,
        key_prefix=f"buyer_{data_choice.replace(' ', '_').lower()}"
    )

    supplier_df = buyer_supplier_df.copy()

    supplier_df["CO2 Intensity"] = pd.to_numeric(
        supplier_df["CO2 Intensity"],
        errors="coerce"
    ).fillna(DEFAULT_FACTOR_NO_DPP)

    supplier_df["Price per Tonne"] = pd.to_numeric(
        supplier_df["Price per Tonne"],
        errors="coerce"
    ).fillna(900)

    supplier_df["Recycled Content"] = pd.to_numeric(
        supplier_df["Recycled Content"],
        errors="coerce"
    ).fillna(0)

    supplier_df["ESG Score"] = supplier_df.apply(
        lambda r: esg_score(
            r["CO2 Intensity"],
            r["Recycled Content"],
            r["DPP Available"],
            r["Certification"]
        ),
        axis=1
    )

    supplier_df["Effective Intensity for CBAM"] = np.where(
        (~supplier_df["DPP Available"])
        | (supplier_df["Certification"].astype(str) == "Unknown")
        | (supplier_df["Route"].astype(str) == "Unknown / No DPP"),
        DEFAULT_FACTOR_NO_DPP,
        supplier_df["CO2 Intensity"]
    )

    supplier_df["2030 CBAM Liability"] = (
        supplier_df["Effective Intensity for CBAM"]
        * annual_volume
        * 100
    )

    supplier_df["Total Cost 2030"] = (
        supplier_df["Price per Tonne"] * annual_volume
        + supplier_df["2030 CBAM Liability"]
    )

    supplier_df["DPP Completeness"] = supplier_df.apply(
        dpp_completeness,
        axis=1
    )

    supplier_df["Carbon Risk"] = pd.cut(
        supplier_df["CO2 Intensity"],
        bins=[-0.1, 0.5, 1.5, 999],
        labels=["Low", "Medium", "High"]
    )

    supplier_df["Recommendation"] = supplier_df.apply(
        lambda r: recommendation(
            r["ESG Score"],
            r["CO2 Intensity"],
            r["DPP Available"]
        ),
        axis=1
    )

    for col in ["ESG Score", "2030 CBAM Liability", "Total Cost 2030", "DPP Completeness"]:
        supplier_df[col] = pd.to_numeric(supplier_df[col], errors="coerce").fillna(0)

    best_esg = supplier_df.sort_values("ESG Score", ascending=False).iloc[0]
    cheapest = supplier_df.sort_values("Total Cost 2030").iloc[0]
    premium = best_esg["Total Cost 2030"] - cheapest["Total Cost 2030"]

    tab1, tab2, tab3 = st.tabs(
        ["Supplier Compare", "ESG Risk Score", "DPP Verification"]
    )

    with tab1:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Best ESG supplier", best_esg["Supplier"])
        k2.metric("Best total cost", cheapest["Supplier"])
        k3.metric("ESG premium", money(premium))
        k4.metric("Within budget?", "Yes" if premium <= budget else "No")

        st.dataframe(
            supplier_df[
                [
                    "Supplier",
                    "Country",
                    "Country Factor Status",
                    "Route",
                    "CO2 Intensity",
                    "Effective Intensity for CBAM",
                    "Recycled Content",
                    "DPP Available",
                    "Certification",
                    "ESG Score",
                    "2030 CBAM Liability",
                    "Total Cost 2030",
                    "Recommendation",
                ]
            ].sort_values("ESG Score", ascending=False),
            use_container_width=True
        )

        fig = px.scatter(
            supplier_df,
            x="Total Cost 2030",
            y="ESG Score",
            size="2030 CBAM Liability",
            color="Recommendation",
            hover_name="Supplier",
            title=f"ESG score vs total cost — {data_choice}"
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        radar_rows = []

        for _, r in supplier_df.iterrows():
            radar_rows.extend([
                {
                    "Supplier": r["Supplier"],
                    "Dimension": "Low Carbon",
                    "Score": max(
                        0,
                        min(100, (2.5 - r["CO2 Intensity"]) / (2.5 - 0.1) * 100)
                    )
                },
                {
                    "Supplier": r["Supplier"],
                    "Dimension": "Recycled Content",
                    "Score": r["Recycled Content"]
                },
                {
                    "Supplier": r["Supplier"],
                    "Dimension": "DPP Quality",
                    "Score": r["DPP Completeness"]
                },
                {
                    "Supplier": r["Supplier"],
                    "Dimension": "Certification",
                    "Score": 100 if r["Certification"] == "Verified"
                    else 50 if r["Certification"] == "Self-declared"
                    else 0
                },
                {
                    "Supplier": r["Supplier"],
                    "Dimension": "Price Value",
                    "Score": max(
                        0,
                        100
                        - (
                            r["Price per Tonne"]
                            - supplier_df["Price per Tonne"].min()
                        )
                        / max(
                            supplier_df["Price per Tonne"].max()
                            - supplier_df["Price per Tonne"].min(),
                            1
                        )
                        * 100
                    )
                },
            ])

        radar = pd.DataFrame(radar_rows)

        fig = go.Figure()

        for supplier in radar["Supplier"].unique():
            sub = radar[radar["Supplier"] == supplier]

            fig.add_trace(
                go.Scatterpolar(
                    r=sub["Score"],
                    theta=sub["Dimension"],
                    fill="toself",
                    name=supplier
                )
            )

        fig.update_layout(
            title=f"ESG radar chart — {data_choice}",
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=True
        )

        st.plotly_chart(fig, use_container_width=True)

        risk_flags = supplier_df[
            [
                "Supplier",
                "Country Factor Status",
                "Carbon Risk",
                "DPP Available",
                "Certification",
                "Recommendation",
            ]
        ]

        st.dataframe(risk_flags, use_container_width=True)

    with tab3:
        supplier_df["Liability without DPP"] = (
            DEFAULT_FACTOR_NO_DPP
            * annual_volume
            * 100
        )

        supplier_df["Default Factor Risk Premium"] = np.maximum(
            supplier_df["Liability without DPP"]
            - supplier_df["2030 CBAM Liability"],
            0
        )

        supplier_df["Liability without DPP"] = pd.to_numeric(
            supplier_df["Liability without DPP"],
            errors="coerce"
        ).fillna(0)

        supplier_df["Default Factor Risk Premium"] = pd.to_numeric(
            supplier_df["Default Factor Risk Premium"],
            errors="coerce"
        ).fillna(0)

        k1, k2, k3 = st.columns(3)
        k1.metric(
            "Avg DPP completeness",
            f"{supplier_df['DPP Completeness'].mean():.1f}%"
        )
        k2.metric(
            "Highest DPP risk premium",
            money(supplier_df["Default Factor Risk Premium"].max())
        )
        k3.metric("Origin verification target", "100%")

        st.dataframe(
            supplier_df[
                [
                    "Supplier",
                    "Country",
                    "Country Factor Status",
                    "DPP Available",
                    "Certification",
                    "DPP Completeness",
                    "CO2 Intensity",
                    "Effective Intensity for CBAM",
                    "Liability without DPP",
                    "2030 CBAM Liability",
                    "Default Factor Risk Premium",
                ]
            ],
            use_container_width=True
        )

        fig = px.bar(
            supplier_df,
            x="Supplier",
            y="Default Factor Risk Premium",
            color="DPP Available",
            title=f"Risk premium from missing or unverified DPP — {data_choice}"
        )

        st.plotly_chart(fig, use_container_width=True)




# ============================================================
# 8. Role dispatch
# ============================================================

if role == "Importer":
    render_importer_view()
elif role == "Manufacturer":
    render_manufacturer_view()
else:
    render_buyer_trader_view()

# ============================================================
# 9. Footer
# ============================================================

st.divider()

st.caption(
    "Model note: the dashboard separates workbook-based records from editable scenario inputs. "
    "Each role has its own scenario controls, and those controls directly drive the "
    "corresponding charts, metrics and decision outputs in that role view."
)
