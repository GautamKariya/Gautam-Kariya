import pandas as pd
import re
import io

def parse_shares_input(file_obj):
    """
    Parses the Shares Input Excel file with FLEXIBLE column mapping based on keywords.
    file_obj: UploadedFile object or file path.
    """
    try:
        # Read the file without header initially to scan rows
        if isinstance(file_obj, str):
            # If it's a file path
            df_raw = pd.read_excel(file_obj, header=None, nrows=50)
        else:
            # If it's a file object (Streamlit UploadedFile)
            df_raw = pd.read_excel(file_obj, header=None, nrows=50)
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
    except Exception as e:
        return None, f"Error reading Excel file: {str(e)}"

    header_row_idx = -1

    # scan first 50 rows to find header
    for i in range(min(50, len(df_raw))):
        row_values = df_raw.iloc[i].astype(str).tolist()
        row_str = " ".join([str(x).lower() for x in row_values])

        # Mandatory keywords to identify header row: "script code" and "isin"
        if "script" in row_str and "code" in row_str and "isin" in row_str:
            header_row_idx = i
            break

    if header_row_idx == -1:
        return None, "Could not find header row with 'Script code' and 'ISIN' in the first 50 rows."

    # Reload with correct header
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)

    df = pd.read_excel(file_obj, header=header_row_idx)

    # --- FLEXIBLE COLUMN MAPPING ---

    # Define mapping rules: (Internal Key, List of Keywords (ALL must be present), List of Excluded Keywords)
    # The order matters for ambiguous columns (e.g. Closing Units vs Closing Amount)
    mapping_rules = [
        ("ISIN", ["isin"], []),
        ("SCRIPT_CODE", ["script", "code"], ["isin"]), # Avoid matching ISIN Code column

        ("OPENING_UNITS", ["opening", "units"], []),
        ("PURCHASE_UNITS", ["purchase", "units"], []),
        ("BONUS_RECD", ["bonus"], []), # flexible for "Bonus Recd" or "Bonus Units"
        ("SALES_UNITS", ["sale", "units"], []), # matches "sales" or "sale"

        ("CLOSING_UNITS", ["closing", "units"], []),

        # Closing Amount: Prioritize explicit Amount/Value, then fallback excluding Rate/Price
        ("CLOSING_AMOUNT", ["closing", "amount"], []),
        ("CLOSING_AMOUNT", ["closing", "value"], []),
        ("CLOSING_AMOUNT", ["closing", "rs"], []),
        ("CLOSING_AMOUNT", ["closing"], ["units", "rate", "price", "qty"]),

        ("MARKET_PRICE", ["mkt", "price"], []),
        ("MARKET_PRICE", ["market", "price"], []),

        ("MARKET_VALUE", ["mkt", "value"], []),
        ("MARKET_VALUE", ["market", "value"], []),

        ("UGL", ["realised", "gain"], []), # Matches "UN-Realised Gain/Loss"
        ("UGL", ["realised", "loss"], []),

        ("DIVIDEND_RECD", ["dividend"], []),

        # Optional Amount columns with strict exclusions to avoid Rate/Price
        # Opening
        ("OPENING_AMOUNT", ["opening", "amount"], []),
        ("OPENING_AMOUNT", ["opening", "value"], []),
        ("OPENING_AMOUNT", ["opening", "cost"], []),
        ("OPENING_AMOUNT", ["opening", "rs"], []),
        ("OPENING_AMOUNT", ["opening"], ["units", "rate", "price", "qty", "no"]), # Fallback

        # Purchase
        ("PURCHASE_AMOUNT", ["purchase", "amount"], []),
        ("PURCHASE_AMOUNT", ["purchase", "value"], []),
        ("PURCHASE_AMOUNT", ["purchase", "cost"], []),
        ("PURCHASE_AMOUNT", ["purchase", "rs"], []),
        ("PURCHASE_AMOUNT", ["purchase"], ["units", "rate", "price", "qty", "no"]), # Fallback

        # Sales
        ("SALES_AMOUNT", ["sale", "amount"], []),
        ("SALES_AMOUNT", ["sale", "value"], []),
        ("SALES_AMOUNT", ["sale", "cost"], []),
        ("SALES_AMOUNT", ["sale", "rs"], []),
        ("SALES_AMOUNT", ["sale"], ["units", "rate", "price", "qty", "no"]) # Fallback
    ]

    # Normalize headers for matching
    # Create a map of original_col_name -> normalized_string
    normalized_headers = {}
    for col in df.columns:
        normalized = str(col).lower().strip()
        # Remove common delimiters to help matching
        normalized = normalized.replace("\n", " ").replace("-", " ").replace("_", " ")
        normalized_headers[col] = normalized

    found_map = {}
    mapped_columns = set() # Keep track of used columns to avoid double mapping

    # Apply rules
    for internal_key, required_keywords, excluded_keywords in mapping_rules:
        # If we already found this internal key, skip (unless we want to overwrite, but first match is usually better if ordered correctly)
        if internal_key in found_map.values():
            continue

        for col, norm in normalized_headers.items():
            if col in mapped_columns:
                continue

            # Check if all required keywords are present
            if all(kw in norm for kw in required_keywords):
                # Check if any excluded keyword is present
                if not any(ex in norm for ex in excluded_keywords):
                    found_map[col] = internal_key
                    mapped_columns.add(col)
                    break # Found a match for this rule, move to next rule

    # Check for Mandatory Columns
    mandatory_keys = [
        "ISIN", "SCRIPT_CODE",
        "OPENING_UNITS", "PURCHASE_UNITS", "BONUS_RECD", "SALES_UNITS", "CLOSING_UNITS",
        "CLOSING_AMOUNT", "UGL"
    ]

    missing_keys = [key for key in mandatory_keys if key not in found_map.values()]

    if missing_keys:
        return None, f"Missing mandatory columns. Could not identify columns for: {', '.join(missing_keys)}. \nDetected Headers: {list(df.columns)}"

    # Rename columns
    df_clean = df.rename(columns=found_map)

    # Filter ISIN
    if 'ISIN' in df_clean.columns:
        df_clean['ISIN'] = df_clean['ISIN'].astype(str).str.strip().str.upper()
        # Remove rows with empty ISIN
        df_clean = df_clean.dropna(subset=['ISIN'])
        # Remove rows where ISIN is not valid (e.g. header repetition or footer)
        df_clean = df_clean[df_clean['ISIN'].str.len() > 5]

    # Filter out "Total" rows if Name column exists (or just based on ISIN validation)
    # Add Name mapping separately as it's loose
    if 'NAME' not in df_clean.columns:
        for col in df.columns:
            if col not in mapped_columns:
                norm = normalized_headers[col]
                if 'name' in norm or 'particulars' in norm or 'script' in norm: # script code is already mapped, so this matches "Script Name"
                     # Be careful not to overwrite
                     df_clean[col] = df[col] # Copy
                     df_clean.rename(columns={col: 'NAME'}, inplace=True)
                     break

    if 'NAME' in df_clean.columns:
         df_clean = df_clean[~df_clean['NAME'].astype(str).str.contains('total', case=False, na=False)]

    # --- Numeric Conversion ---
    numeric_cols = [
        'OPENING_UNITS', 'PURCHASE_UNITS', 'BONUS_RECD', 'SALES_UNITS', 'CLOSING_UNITS',
        'CLOSING_AMOUNT', 'DIVIDEND_RECD', 'UGL',
        'MARKET_VALUE', 'MARKET_PRICE', 'OPENING_AMOUNT', 'PURCHASE_AMOUNT', 'SALES_AMOUNT'
    ]

    for col in numeric_cols:
        if col in df_clean.columns:
            # Clean string and convert
            s = df_clean[col].astype(str)
            s = s.str.replace(',', '', regex=False).str.strip()
            # Handle " - " or empty as 0
            s = s.replace(['-', '', 'nan', 'None'], '0')
            df_clean[col] = pd.to_numeric(s, errors='coerce').fillna(0.0)
        else:
            # Create missing numeric columns as 0.0 (except mandatory ones which we checked)
            df_clean[col] = 0.0

    return df_clean, None
