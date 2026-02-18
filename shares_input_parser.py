import pandas as pd
import re

def clean_column_name(col):
    if not isinstance(col, str):
        return ""
    return re.sub(r'\s+', ' ', col).strip().lower()

def parse_shares_input(file_obj):
    """
    Parses the Shares Input Excel file.
    file_obj: UploadedFile object or file path.
    """
    try:
        # Read the file without header initially to scan rows
        # Use openpyxl or xlrd automatically
        df_raw = pd.read_excel(file_obj, header=None, nrows=50)
    except Exception as e:
        return None, f"Error reading Excel file: {str(e)}"

    header_row_idx = -1

    # scan first 50 rows
    for i in range(min(50, len(df_raw))):
        row_values = df_raw.iloc[i].astype(str).tolist()
        row_str = " ".join([str(x).lower() for x in row_values])

        # Mandatory keywords to identify header row
        if "script code" in row_str and "isin" in row_str:
            header_row_idx = i
            break

    if header_row_idx == -1:
        return None, "Could not find header row with 'Script code' and 'ISIN' in the first 50 rows."

    # Reload with correct header
    # Note: Streamlit file objects need to be reset if read multiple times,
    # but pandas read_excel usually handles bytes.
    # If file_obj is a stream, seek(0) might be needed.
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)

    df = pd.read_excel(file_obj, header=header_row_idx)

    # Define mapping logic
    # We want to find column names in df.columns that match our keywords

    # Standard internal names
    # script_code, isin, name, opening_units, bonus_recd, closing_units, closing_amount,
    # market_price, market_value, ugl, dividend_recd

    found_cols = {}

    for col in df.columns:
        col_clean = clean_column_name(str(col))

        # Priority checks
        if 'script code' in col_clean:
            found_cols['script_code'] = col
        elif 'isin' in col_clean:
            found_cols['isin'] = col
        elif 'name of investment' in col_clean or 'scrip name' in col_clean:
            found_cols['name'] = col

        # Closing Units vs Amount
        elif 'closing' in col_clean:
            if 'amount' in col_clean or 'value' in col_clean:
                found_cols['closing_amount'] = col
            elif 'units' in col_clean or 'qty' in col_clean:
                found_cols['closing_units'] = col
            else:
                # Ambiguous 'Closing as on...' usually implies units if just 'Closing'
                if 'closing_units' not in found_cols:
                    found_cols['closing_units'] = col

        # Opening
        elif 'opening' in col_clean:
            if 'units' in col_clean or 'qty' in col_clean or 'balance' in col_clean:
                found_cols['opening_units'] = col

        # Bonus
        elif 'bonus' in col_clean:
            if 'recd' in col_clean or 'units' in col_clean:
                found_cols['bonus_recd'] = col

        # Dividend
        elif 'dividend' in col_clean or 'div recd' in col_clean:
            found_cols['dividend_recd'] = col

        # Market Price
        elif 'mkt price' in col_clean or 'market price' in col_clean:
            found_cols['market_price'] = col

        # Market Value
        elif 'mkt value' in col_clean or 'market value' in col_clean:
            found_cols['market_value'] = col

        # UGL
        elif 'un-realised' in col_clean or 'unrealised' in col_clean or 'unrealized' in col_clean:
            found_cols['ugl'] = col

    # Check mandatory columns
    missing = [k for k in ['script_code', 'isin', 'opening_units', 'closing_units'] if k not in found_cols]
    if missing:
        # Fallback: if 'name' is missing, that's okay, but others are critical
        return None, f"Missing columns: {', '.join(missing)}"

    # Select and Rename
    df_clean = df[list(found_cols.values())].copy()
    df_clean.columns = list(found_cols.keys())

    # Filter Rows
    # 1. ISIN starts with INE
    if 'isin' in df_clean.columns:
        df_clean['isin'] = df_clean['isin'].astype(str).str.strip().str.upper()
        # Drop rows where ISIN is NaN or not string
        df_clean = df_clean.dropna(subset=['isin'])
        df_clean = df_clean[df_clean['isin'].str.startswith('INE')]

    # 2. Exclude Total rows (if name column exists)
    if 'name' in df_clean.columns:
        df_clean = df_clean[~df_clean['name'].astype(str).str.contains('total', case=False, na=False)]

    # Standardize Numerics
    numeric_cols = ['opening_units', 'bonus_recd', 'closing_units', 'closing_amount',
                    'market_price', 'market_value', 'ugl', 'dividend_recd']

    for col in numeric_cols:
        if col not in df_clean.columns:
            df_clean[col] = 0.0
        else:
             # Remove commas, spaces, convert to numeric
             # Force string conversion first to handle mixed types
             s = df_clean[col].astype(str)
             s = s.str.replace(',', '').str.replace(' ', '')
             # handle 'nan' string
             s = pd.to_numeric(s, errors='coerce').fillna(0.0)
             df_clean[col] = s

    return df_clean, None
