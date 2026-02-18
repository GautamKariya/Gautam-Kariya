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
    df.columns = [c.strip() for c in df.columns]

    # Check for required columns: ISIN, CLOSE, SERIES
    # The user mentioned columns by name: ISIN (M), CLOSE (F), SERIES (B)
    # But usually files have headers. We will use headers.

    req_cols = ['ISIN', 'SERIES', 'CLOSE']
    col_map = {c.lower(): c for c in df.columns}

    final_cols = {}
    for rc in req_cols:
        if rc.lower() in col_map:
            final_cols[rc] = col_map[rc.lower()]

    if len(final_cols) < len(req_cols):
        missing = [rc for rc in req_cols if rc.lower() not in col_map]
        return None, f"Missing columns in Bhav Copy CSV: {', '.join(missing)}"

    df = df.rename(columns={v: k for k, v in final_cols.items()})

    # Filter for SERIES == 'EQ'
    # Important: Do this BEFORE dropping duplicates or anything else
    df['SERIES'] = df['SERIES'].astype(str).str.strip().str.upper()

    # Filter EQ
    df_eq = df[df['SERIES'] == 'EQ'].copy()

    # Check if empty after filter
    if df_eq.empty:
        # Maybe no EQ rows? Warn but return empty?
        pass

    # Extract ISIN and CLOSE
    # Convert CLOSE to numeric
    df_eq['CLOSE'] = pd.to_numeric(df_eq['CLOSE'], errors='coerce')

    # Clean ISIN
    df_eq['ISIN'] = df_eq['ISIN'].astype(str).str.strip().str.upper()

    # Select final columns
    # We want ISIN -> CLOSE map.
    # Drop NaNs in CLOSE or ISIN
    df_clean = df_eq[['ISIN', 'CLOSE']].dropna()
    df_clean = df_clean.rename(columns={'CLOSE': 'bhav_close'})

    # Handle duplicates (should be unique for EQ series per ISIN)
    # If duplicates exist for EQ, take the first/last? Usually unique.
    df_clean = df_clean.drop_duplicates(subset=['ISIN'], keep='last')

    return df_clean, None
