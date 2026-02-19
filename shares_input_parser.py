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

    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)

    df = pd.read_excel(file_obj, header=header_row_idx)

    found_cols = {}

    for col in df.columns:
        col_clean = clean_column_name(str(col))

        # Identity Columns
        if 'script code' in col_clean:
            found_cols['script_code'] = col
        elif 'isin' in col_clean:
            found_cols['isin'] = col
        elif 'name of investment' in col_clean or 'scrip name' in col_clean:
            found_cols['name'] = col

        # Opening
        elif 'opening' in col_clean:
            if 'amount' in col_clean or 'value' in col_clean:
                found_cols['opening_amount'] = col
            elif 'units' in col_clean or 'qty' in col_clean or 'balance' in col_clean:
                found_cols['opening_units'] = col

        # Purchase
        elif 'purchase' in col_clean:
            if 'amount' in col_clean or 'value' in col_clean:
                found_cols['purchase_amount'] = col
            elif 'units' in col_clean or 'qty' in col_clean:
                found_cols['purchase_units'] = col

        # Sales
        elif 'sale' in col_clean: # sale or sales
            if 'amount' in col_clean or 'value' in col_clean:
                found_cols['sales_amount'] = col
            elif 'units' in col_clean or 'qty' in col_clean:
                found_cols['sales_units'] = col

        # Bonus
        elif 'bonus' in col_clean:
            if 'recd' in col_clean or 'units' in col_clean:
                found_cols['bonus_recd'] = col

        # Closing
        elif 'closing' in col_clean:
            if 'amount' in col_clean or 'value' in col_clean:
                found_cols['closing_amount'] = col
            elif 'units' in col_clean or 'qty' in col_clean:
                found_cols['closing_units'] = col
            else:
                if 'closing_units' not in found_cols:
                    found_cols['closing_units'] = col

        # Dividend
        elif 'dividend' in col_clean or 'div recd' in col_clean:
            found_cols['dividend_recd'] = col

        # Market Price
        elif 'mkt price' in col_clean or 'market price' in col_clean:
            found_cols['market_price'] = col

        # Market Value
        elif 'mkt value' in col_clean or 'market value' in col_clean:
            found_cols['market_value'] = col

        # UGL (Optional, but useful to have)
        elif 'un-realised' in col_clean or 'unrealised' in col_clean or 'unrealized' in col_clean:
            found_cols['ugl'] = col

    # Check mandatory columns
    missing = [k for k in ['script_code', 'isin', 'opening_units', 'closing_units'] if k not in found_cols]
    if missing:
        return None, f"Missing columns: {', '.join(missing)}"

    # Select and Rename
    df_clean = df[list(found_cols.values())].copy()
    df_clean.columns = list(found_cols.keys())

    # Filter Rows
    if 'isin' in df_clean.columns:
        df_clean['isin'] = df_clean['isin'].astype(str).str.strip().str.upper()
        df_clean = df_clean.dropna(subset=['isin'])
        # User said "Work for Any listed security", but originally "Process only ISIN starting with INE".
        # Current prompt "ISIN is unique... works for EQ, RR, BE". All start with INE/INF/IN.
        # Let's keep strict ISIN format check but allow all IN*.
        df_clean = df_clean[df_clean['isin'].str.startswith('IN')]

    if 'name' in df_clean.columns:
        df_clean = df_clean[~df_clean['name'].astype(str).str.contains('total', case=False, na=False)]

    # Standardize Numerics
    # Add potentially missing optional columns with 0
    all_numeric_cols = [
        'opening_units', 'opening_amount',
        'purchase_units', 'purchase_amount',
        'sales_units', 'sales_amount',
        'bonus_recd',
        'closing_units', 'closing_amount',
        'market_price', 'market_value', 'ugl', 'dividend_recd'
    ]

    for col in all_numeric_cols:
        if col not in df_clean.columns:
            df_clean[col] = 0.0
        else:
             s = df_clean[col].astype(str)
             s = s.str.replace(',', '').str.replace(' ', '')
             s = pd.to_numeric(s, errors='coerce').fillna(0.0)
             df_clean[col] = s

    return df_clean, None
