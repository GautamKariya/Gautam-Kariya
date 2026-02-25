import pandas as pd

def parse_bhav_copy(file_obj):
    """
    Parses NSE Bhav Copy CSV.
    file_obj: UploadedFile or path.
    """
    try:
        df = pd.read_csv(file_obj)
    except Exception as e:
        return None, f"Error reading Bhav Copy CSV: {str(e)}"

    # Standardize column names
    df.columns = [str(c).strip() for c in df.columns]

    # Required columns check: ISIN, CLOSE
    # User said: "ISIN (M), CLOSE (F)" - but headers should be present
    req_cols = ['ISIN', 'CLOSE']
    col_map = {c.lower(): c for c in df.columns}

    final_cols = {}
    for rc in req_cols:
        if rc.lower() in col_map:
            final_cols[rc] = col_map[rc.lower()]

    if len(final_cols) < len(req_cols):
        missing = [rc for rc in req_cols if rc.lower() not in col_map]
        return None, f"Missing columns in Bhav Copy CSV: {', '.join(missing)}"

    df = df.rename(columns={v: k for k, v in final_cols.items()})

    # Clean data
    df['ISIN'] = df['ISIN'].astype(str).str.strip().str.upper()
    df['CLOSE'] = pd.to_numeric(df['CLOSE'], errors='coerce')

    # Drop rows where required columns are NaN
    df = df.dropna(subset=['ISIN', 'CLOSE'])

    # Rename for internal consistency
    df = df.rename(columns={'CLOSE': 'bhav_close'})

    # Handle duplicates: Keep last?
    # User said "ISIN is unique across all series" (for listing purposes).
    # But technically multiple series rows can exist for same ISIN in daily bhav copy (e.g. EQ and BL).
    # Usually we want EQ price if available, but user said "Do NOT filter by SERIES".
    # And "ISIN uniquely identifies the security".
    # If duplicates exist, which price to take?
    # Assuming standard trading series is what we want.
    # If we just drop duplicates keeping last, it's arbitrary which series we get if unsorted.
    # But usually ISINs are unique enough for standard valuation.
    # Let's trust the user "ISIN is unique".

    df = df.drop_duplicates(subset=['ISIN'], keep='last')

    return df[['ISIN', 'bhav_close']], None
