import pandas as pd
import re

def parse_shares_input(file_obj):
    """
    Parses the Shares Input Excel file with STRICT column mapping.
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

    # --- STRICT COLUMN MAPPING & CLEANING ---
    # 1. Normalize Header: Strip spaces
    df.columns = df.columns.str.strip()

    # 2. Define Exact Mapping (File Header -> Internal Key)
    # Internal Keys must match those used in shares_engine.py (Uppercase)
    col_map = {
        "ISIN": "ISIN",
        "Script Code": "SCRIPT_CODE",
        "Opening Units": "OPENING_UNITS",
        "Purchase Units": "PURCHASE_UNITS",
        "Bonus Units": "BONUS_RECD", # Mapped to BONUS_RECD
        "Sales Units": "SALES_UNITS",
        "Closing Units": "CLOSING_UNITS",
        "Closing Amount": "CLOSING_AMOUNT",
        "Dividend Received": "DIVIDEND_RECD",
        "UN- Realised Gain/Loss": "UGL"
    }

    # 3. Add Optional/Extra columns if needed?
    # Market Value and Market Price are needed for other modules.
    # User didn't list them in "EXACT COLUMN NAMES" list for Closing Unit logic, but engine needs them.
    # Assuming standard names or similar:
    # "Mkt Value ..." -> MARKET_VALUE
    # "MKT PRICE ..." -> MARKET_PRICE
    # I'll keep the previous flexible logic for these non-strict columns, or look for exacts?
    # User said "The Shares.xlsx input file structure is FIXED."
    # But only listed the columns relevant to the failure (Units/UGL).
    # I will look for Market Price/Value flexibly to ensure engine doesn't break.

    # Apply Strict Mapping
    found_map = {}
    missing = []

    for file_col, internal_col in col_map.items():
        if file_col in df.columns:
            found_map[file_col] = internal_col
        else:
            # Fallback for "UN- Realised Gain/Loss" spacing variations?
            # User said: "Match keywords... OR simply match 'UN- Realised Gain/Loss'... Case sensitive after normalization."
            # "UN- Realised Gain/Loss" is the target.
            missing.append(file_col)

    if missing:
        return None, f"Missing mandatory columns (Exact Match): {', '.join(missing)}"

    # Rename Strict Columns
    df_clean = df.rename(columns=found_map)

    # 4. Handle other columns (Market Price, Market Value, Opening/Purchase/Sales Amount) flexibly
    # We need these for full engine function.
    # Strategy: Scan remaining columns for keywords and map to internal keys IF NOT ALREADY MAPPED.

    remaining_cols = [c for c in df.columns if c not in found_map]
    flexible_map = {}

    for col in remaining_cols:
        col_clean = str(col).strip().lower()

        if 'mkt price' in col_clean or 'market price' in col_clean:
            flexible_map[col] = 'MARKET_PRICE'
        elif 'mkt value' in col_clean or 'market value' in col_clean:
            flexible_map[col] = 'MARKET_VALUE'
        elif 'opening' in col_clean and ('amount' in col_clean or 'value' in col_clean):
            flexible_map[col] = 'OPENING_AMOUNT'
        elif 'purchase' in col_clean and ('amount' in col_clean or 'value' in col_clean):
            flexible_map[col] = 'PURCHASE_AMOUNT'
        elif 'sale' in col_clean and ('amount' in col_clean or 'value' in col_clean):
            flexible_map[col] = 'SALES_AMOUNT'

    df_clean = df_clean.rename(columns=flexible_map)

    # 5. Filter ISIN
    if 'ISIN' in df_clean.columns:
        df_clean['ISIN'] = df_clean['ISIN'].astype(str).str.strip().str.upper()
        df_clean = df_clean.dropna(subset=['ISIN'])

    # 6. Exclude Total
    if 'NAME' in df_clean.columns: # Wait, Name column?
        # User didn't specify Name column in strict list.
        # But engine uses 'NAME'.
        # Usually "Name of Investment" or "Scrip Name".
        pass

    # Try to find Name column if not in strict list
    if 'NAME' not in df_clean.columns:
        for col in df.columns:
            if 'name' in str(col).lower() and 'investment' in str(col).lower():
                df_clean[col] = df[col] # Copy over
                df_clean = df_clean.rename(columns={col: 'NAME'})
                break

    if 'NAME' in df_clean.columns:
        df_clean = df_clean[~df_clean['NAME'].astype(str).str.contains('total', case=False, na=False)]

    # 7. Numeric Conversion (Strict & Robust)
    numeric_cols = [
        'OPENING_UNITS', 'PURCHASE_UNITS', 'BONUS_RECD', 'SALES_UNITS', 'CLOSING_UNITS',
        'CLOSING_AMOUNT', 'DIVIDEND_RECD', 'UGL',
        'MARKET_VALUE', 'MARKET_PRICE', 'OPENING_AMOUNT', 'PURCHASE_AMOUNT', 'SALES_AMOUNT'
    ]

    for col in numeric_cols:
        if col not in df_clean.columns:
            df_clean[col] = 0.0
        else:
            s = df_clean[col].astype(str)
            s = s.str.replace(',', '').str.strip()
            # Coerce to numeric, fill NaN with 0
            df_clean[col] = pd.to_numeric(s, errors='coerce').fillna(0.0)

    return df_clean, None
