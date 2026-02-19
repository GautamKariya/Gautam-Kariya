import pandas as pd

def parse_bhav_copy(file_obj):
    """
    Parses NSE Bhav Copy CSV.
    file_obj: UploadedFile or path.
    """
    try:
        # Read full file
        df = pd.read_csv(file_obj)
    except Exception as e:
        return None, f"Error reading Bhav Copy CSV: {str(e)}"

    # Standardize column names (strip whitespace)
    df.columns = [str(c).strip() for c in df.columns]

    # Check for required columns: ISIN, CLOSE, SERIES
    # User specified columns: ISIN, CLOSE, SERIES
    req_cols = ['ISIN', 'SERIES', 'CLOSE']
    col_map = {c.lower(): c for c in df.columns}

    final_cols = {}
    for rc in req_cols:
        if rc.lower() in col_map:
            final_cols[rc] = col_map[rc.lower()]

    if len(final_cols) < len(req_cols):
        missing = [rc for rc in req_cols if rc.lower() not in col_map]
        return None, f"Missing columns in Bhav Copy CSV: {', '.join(missing)}"

    # Rename to standard
    df = df.rename(columns={v: k for k, v in final_cols.items()})

    # Clean data (String columns)
    # Strip whitespace from ISIN and SERIES
    df['ISIN'] = df['ISIN'].astype(str).str.strip().str.upper()
    df['SERIES'] = df['SERIES'].astype(str).str.strip().str.upper()

    # Convert CLOSE to numeric
    # Handle non-numeric gracefully (coerce to NaN then drop?)
    # CLOSE should be float.
    df['CLOSE'] = pd.to_numeric(df['CLOSE'], errors='coerce')

    # Drop rows where required columns are NaN
    df = df.dropna(subset=['ISIN', 'SERIES', 'CLOSE'])

    # Print Debug info (first 5 rows)
    # print("DEBUG: Bhav Copy First 5 Rows:")
    # print(df.head())
    # print("DEBUG: Bhav Copy Columns:", df.columns.tolist())

    # Return Full DataFrame (ISIN, SERIES, CLOSE)
    # We rename CLOSE to bhav_close to be explicit, but user said "Return CLOSE column value".
    # I'll stick to 'CLOSE' or just map it later. Let's rename to match internal standard 'bhav_close'.
    df = df.rename(columns={'CLOSE': 'bhav_close'})

    # Select only needed columns?
    # No, keep full just in case user wants more info later? But strict is better.
    return df[['ISIN', 'SERIES', 'bhav_close']], None
