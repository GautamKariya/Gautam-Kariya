import pandas as pd
import logging

def parse_shares_input_file(file):
    """
    Parses the Shares Input Excel ("Shares" sheet).

    Extracts:
    - Script Code
    - ISIN CODE
    - Closing Units
    - Closing Amount (Cost)
    - Market Price
    - Market Value
    - UN-Realised Gain/Loss
    - Dividend Received
    - Bonus Recd During The Period (Units)

    Args:
        file: Excel file object.

    Returns:
        pd.DataFrame: Columns ['Script Code', 'ISIN', 'Closing Units', 'Closing Amount', 'Market Price', 'Market Value', 'UGL', 'Dividend Received', 'Bonus Received']
    """
    logging.info("Starting Shares Input Parsing.")

    try:
        # Load File
        xls = None
        try:
             xls = pd.ExcelFile(file)
        except Exception:
             # Fallback for old xls
             file.seek(0)
             xls = pd.ExcelFile(file, engine='xlrd')

        sheet_name = None
        for name in xls.sheet_names:
            if "SHARES" in name.upper():
                sheet_name = name
                break

        if not sheet_name:
            raise ValueError(f"Sheet 'SHARES' not found.")

        # Scan for header
        df_scan = pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=50)

        header_idx = None
        for i, row in df_scan.iterrows():
            row_str = " ".join([str(x) for x in row if pd.notna(x)]).lower()
            # Must contain "script" AND "code" AND "isin"
            if "script" in row_str and "code" in row_str and "isin" in row_str:
                header_idx = i
                break

        if header_idx is None:
            # Fallback search without ISIN check? No, strictly required.
            raise ValueError("Header row not found (looked for 'Script', 'Code', 'ISIN').")

        # Read Data
        # Read *all* columns first, then map
        df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=header_idx)

        # Identify Columns dynamically
        col_map = {}

        # Helper to find column
        def find_col(df, keywords, anti_keywords=[]):
            for col in df.columns:
                c_str = str(col).lower()
                if all(k in c_str for k in keywords) and not any(ak in c_str for ak in anti_keywords):
                    return col
            return None

        # Script Code
        col_map['Script Code'] = find_col(df_raw, ['script', 'code'])
        # ISIN
        col_map['ISIN'] = find_col(df_raw, ['isin'])
        # Closing Units
        col_map['Closing Units'] = find_col(df_raw, ['closing', 'units'])
        # Closing Amount
        col_map['Closing Amount'] = find_col(df_raw, ['closing', 'amount'])

        # Market Price (MKT PRICE...)
        # Avoid "Mkt Value"
        col_map['Market Price'] = find_col(df_raw, ['mkt', 'price'], anti_keywords=['value'])
        if not col_map['Market Price']:
             col_map['Market Price'] = find_col(df_raw, ['market', 'price'], anti_keywords=['value'])

        # Market Value
        col_map['Market Value'] = find_col(df_raw, ['mkt', 'value'])
        if not col_map['Market Value']:
             col_map['Market Value'] = find_col(df_raw, ['market', 'value'])

        # UGL
        col_map['UGL'] = find_col(df_raw, ['un', 'realised'])
        # Dividend Received
        col_map['Dividend Received'] = find_col(df_raw, ['dividend', 'received'])
        # Bonus Received
        col_map['Bonus Received'] = find_col(df_raw, ['bonus', 'recd', 'units'])

        # Check required columns
        required = ['Script Code', 'ISIN', 'Closing Units', 'Closing Amount', 'Market Price', 'Market Value', 'UGL', 'Dividend Received', 'Bonus Received']

        # Build final DF
        final_df = pd.DataFrame()
        missing = []

        for req_col in required:
            source_col = col_map.get(req_col)
            if source_col:
                final_df[req_col] = df_raw[source_col]
            else:
                missing.append(req_col)

        if missing:
            logging.error(f"Missing columns: {missing}")
            # Log available columns for debugging
            logging.error(f"Available columns: {df_raw.columns.tolist()}")
            raise ValueError(f"Missing columns in Shares Input: {', '.join(missing)}")

        # Filter Rows (Drop rows where Script Code is NaN or "Total")
        final_df = final_df[final_df['Script Code'].notna()]
        final_df = final_df[~final_df['Script Code'].astype(str).str.contains("Total", case=False, na=False)]

        # Clean Data (Numeric conversion)
        numeric_cols = ['Closing Units', 'Closing Amount', 'Market Price', 'Market Value', 'UGL', 'Dividend Received', 'Bonus Received']
        for col in numeric_cols:
            # Remove commas and convert
            # Also handle if column is object type
            if final_df[col].dtype == object:
                 final_df[col] = final_df[col].astype(str).str.replace(',', '', regex=False)
            final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0.0)

        return final_df

    except Exception as e:
        logging.error(f"Error parsing Shares Input: {e}")
        raise e
