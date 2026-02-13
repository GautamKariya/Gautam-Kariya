import pandas as pd
import logging
import re

def parse_working_file(file):
    """
    Parses the user's Working File (Excel) to extract holdings.

    Args:
        file (file-like object): The uploaded Excel file.

    Returns:
        pd.DataFrame: A DataFrame with aggregated holdings by Script Code.
                      Columns: ['Script Code', 'Script Name', 'Total Quantity', 'Details']
    """
    try:
        # Load the Excel file, specifically the "Shares" sheet
        # Use openpyxl engine
        xls = pd.ExcelFile(file, engine='openpyxl')

        if "Shares" not in xls.sheet_names:
            logging.error("Sheet 'Shares' not found in the Working File.")
            return pd.DataFrame()

        df = pd.read_excel(xls, sheet_name="Shares", header=None)

        # Locate the header row
        header_row_idx = None
        for i, row in df.iterrows():
            # Convert row to string and check for key columns
            row_str = " ".join([str(x) for x in row if pd.notna(x)])
            if "Script code" in row_str and "Name of Investment" in row_str:
                header_row_idx = i
                break

        if header_row_idx is None:
            logging.error("Could not find the header row in 'Shares' sheet.")
            return pd.DataFrame()

        # Reload with correct header
        df = pd.read_excel(xls, sheet_name="Shares", header=header_row_idx)

        # Identify necessary columns
        script_code_col = None
        script_name_col = None
        qty_col = None

        for col in df.columns:
            col_str = str(col).strip()
            if "Script code" in col_str:
                script_code_col = col
            elif "Name of Investment" in col_str:
                script_name_col = col
            elif "Closing" in col_str and "(units)" in col_str:
                qty_col = col

        if not all([script_code_col, script_name_col, qty_col]):
            logging.error(f"Missing required columns. Found: Code={script_code_col}, Name={script_name_col}, Qty={qty_col}")
            return pd.DataFrame()

        # Clean Data
        df = df[[script_code_col, script_name_col, qty_col]].copy()
        df.columns = ['Script Code', 'Script Name', 'Quantity']

        # Remove rows where Script Code is NaN or empty
        df = df.dropna(subset=['Script Code'])

        # Ensure Script Code is treated as integer/string (remove .0 if present)
        df['Script Code'] = pd.to_numeric(df['Script Code'], errors='coerce').fillna(0).astype(int)
        df = df[df['Script Code'] > 0] # Filter out 0 or invalid codes

        # Ensure Quantity is numeric
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0)

        # Group by Script Code
        # We want to aggregate Quantity, but keep the first Script Name
        # We also want to keep a list of 'Details' (e.g. "ONGC", "ONGC (Bonus)") for audit

        def aggregate_details(group):
            details = []
            for _, row in group.iterrows():
                details.append(f"{row['Script Name']} ({row['Quantity']})")
            return "; ".join(details)

        aggregated = df.groupby('Script Code').agg({
            'Script Name': 'first',
            'Quantity': 'sum'
        }).reset_index()

        # Add details column separately (agg can be tricky with custom functions on multiple cols)
        # Re-merge details
        details_series = df.groupby('Script Code').apply(aggregate_details)
        aggregated['Details'] = aggregated['Script Code'].map(details_series)

        logging.info(f"Successfully parsed {len(aggregated)} unique scripts from Working File.")
        return aggregated

    except Exception as e:
        logging.error(f"Error parsing Working File: {e}")
        return pd.DataFrame()
