# SteelCBAM DPP Dashboard — Volume-adjusted version

This version updates the Importer Cost Calculator so that the country-level CBAM chart can respond to changes in the sidebar `Annual volume (tonnes)` input.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Required data file

Place `cbam_final_data.xlsx` in the same folder as `app.py`.
