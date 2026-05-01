# SteelCBAM DPP Dashboard — Role-sensitive Controls

This version ensures that each role's sidebar inputs drive the corresponding charts and metrics.

## Key fixes

### Importer
- Annual volume and budget are role-specific.
- Supplier inputs affect Cost Calculator scenario charts, Forecast charts and DPP charts.
- Route changes reset the default CO2 intensity by using a route-sensitive widget key.
- Forecast charts can display either CBAM liability or total cost, so price changes are visible.

### Manufacturer
- Production volume is role-specific.
- Route, Scope 1, Scope 2 and production volume affect Carbon Price Impact charts.
- DPP issuance, certificate rate and recycled content affect DPP Issuance charts.

### Buyer / Trader
- Annual volume, budget and supplier inputs are role-specific.
- Supplier inputs affect ESG score, total cost, DPP verification, radar chart and procurement recommendation.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Required data

Place `cbam_final_data.xlsx` in the same folder as `app.py`.
