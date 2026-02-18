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

    # Check for required columns
    req_cols = ['ISIN', 'SERIES', 'CLOSE']
    missing = [c for c in req_cols if c not in df.columns]

    if missing:
        # Try finding them case-insensitively
        col_map = {c.lower(): c for c in df.columns}
        remapped = {}
        for rc in req_cols:
            if rc.lower() in col_map:
                remapped[col_map[rc.lower()]] = rc

        if len(remapped) < len(req_cols):
            return None, f"Missing columns in Bhav Copy CSV: {', '.join([c for c in req_cols if c not in remapped.values()])}"

        df = df.rename(columns=remapped)

    # Filter for SERIES == 'EQ'
    # Check if 'SERIES' column exists (it should now)
    if 'SERIES' in df.columns:
        df['SERIES'] = df['SERIES'].astype(str).str.strip().str.upper()
        df = df[df['SERIES'] == 'EQ']

    # Extract ISIN and CLOSE
    # Convert CLOSE to numeric
    if 'CLOSE' in df.columns:
        df['CLOSE'] = pd.to_numeric(df['CLOSE'], errors='coerce')

    # Clean ISIN
    if 'ISIN' in df.columns:
        df['ISIN'] = df['ISIN'].astype(str).str.strip().str.upper()

    # Select final columns
    df_clean = df[['ISIN', 'CLOSE']].dropna()
    df_clean = df_clean.rename(columns={'CLOSE': 'bhav_close'})

    # Handle duplicates (should be unique for EQ series per ISIN)
    # But just in case, take the first one
    df_clean = df_clean.drop_duplicates(subset=['ISIN'])

    return df_clean, None
