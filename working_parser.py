import pandas as pd
import logging
import re

def parse_client_working_v2(file, previous_file=None):
    """
    Parses the Client Working Excel ("Shares" sheet).
    Handles Cumulative Dividends by optionally subtracting Previous Quarter values.

    Args:
        file: Current Quarter Excel file.
        previous_file: Previous Quarter Excel file (Optional).

    Returns:
        pd.DataFrame: Columns ['Investment Name', 'Base Name', 'Closing Units', 'Quarterly Dividend', 'Is Bonus']
    """
    logging.info("Starting Client Working File parsing (v2).")

    def load_shares_sheet(f):
        try:
            xls = pd.ExcelFile(f, engine='openpyxl')
            if "Shares" not in xls.sheet_names:
                logging.error("Sheet 'Shares' not found.")
                return pd.DataFrame()

            # Read first few rows to find header
            df = pd.read_excel(xls, sheet_name="Shares", header=None)

            header_idx = None
            for i, row in df.iterrows():
                row_str = " ".join([str(x) for x in row if pd.notna(x)]).lower()
                # Look for key columns: "Investment", "Dividend", "Closing" or "Quantity"
                if "investment" in row_str and "dividend" in row_str:
                    header_idx = i
                    break

            if header_idx is None:
                logging.error("Header row not found in Shares sheet.")
                return pd.DataFrame()

            df = pd.read_excel(xls, sheet_name="Shares", header=header_idx)
            return df
        except Exception as e:
            logging.error(f"Error reading Excel: {e}")
            return pd.DataFrame()

    # Load Current
    df_curr = load_shares_sheet(file)
    if df_curr.empty:
        return df_curr

    # Load Previous (if exists)
    df_prev = pd.DataFrame()
    if previous_file:
        df_prev = load_shares_sheet(previous_file)

    # Identify Columns in Current
    # We need: Investment Name, Closing Units, Dividend (Cumulative)
    name_col = next((c for c in df_curr.columns if "name" in str(c).lower() and "investment" in str(c).lower()), None)
    qty_col = next((c for c in df_curr.columns if ("closing" in str(c).lower() and "units" in str(c).lower()) or "qty" in str(c).lower() or "quantity" in str(c).lower()), None)
    div_col = next((c for c in df_curr.columns if "dividend" in str(c).lower()), None)

    if not all([name_col, qty_col, div_col]):
        logging.error(f"Missing columns. Name: {name_col}, Qty: {qty_col}, Div: {div_col}")
        return pd.DataFrame()

    # Process Data
    result_data = []

    # Create a map of Previous Cumulative Dividends if available
    # Map: Base Name -> Dividend Value
    prev_div_map = {}
    if not df_prev.empty:
        # We need to identify columns for prev file too
        p_name_col = next((c for c in df_prev.columns if "name" in str(c).lower() and "investment" in str(c).lower()), None)
        p_div_col = next((c for c in df_prev.columns if "dividend" in str(c).lower()), None)

        if p_name_col and p_div_col:
            for _, row in df_prev.iterrows():
                raw_name = str(row[p_name_col])
                # Clean name to get Base Name
                base_name = raw_name.upper().replace("(BONUS)", "").strip()
                try:
                    val = float(row[p_div_col])
                    # If duplicate base names exist (e.g. bonus rows), usually dividend is on the main row.
                    # Or if it's cumulative, we might just take the max or first non-zero?
                    # User said: "Dividend is stored once and increases over time."
                    # We store it.
                    if base_name not in prev_div_map:
                         prev_div_map[base_name] = val
                    else:
                        # If we already have it, maybe sum it?
                        # Or assume it's the same investment split in rows?
                        # Usually dividend is per script.
                        # Let's keep the largest value found for that script to be safe (cumulative)
                        prev_div_map[base_name] = max(prev_div_map[base_name], val)
                except (ValueError, TypeError):
                    pass

    for _, row in df_curr.iterrows():
        raw_name = str(row[name_col])
        if pd.isna(raw_name) or raw_name.strip() == "":
            continue

        # 1. Base Name Logic
        base_name = raw_name.upper().replace("(BONUS)", "").strip()
        is_bonus = "(BONUS)" in raw_name.upper()

        # 2. Extract Values
        try:
            qty = float(row[qty_col])
        except (ValueError, TypeError):
            qty = 0.0

        try:
            curr_cum_div = float(row[div_col])
        except (ValueError, TypeError):
            curr_cum_div = 0.0

        # 3. Quarterly Dividend Calculation
        # Only calculate if it's NOT a bonus row (Bonus rows don't carry dividend usually, but user said "Dividend is stored once")
        # If this row has dividend, we process it.

        quarterly_div = 0.0

        if curr_cum_div > 0:
            prev_cum_div = prev_div_map.get(base_name, 0.0)
            quarterly_div = curr_cum_div - prev_cum_div

            # If negative, something is wrong (maybe sold?), default to 0 or keep negative to flag exception?
            # User said: "Quarter Dividend = Current Cumulative – Previous Cumulative"
            # We'll keep it as is.

        result_data.append({
            'Investment Name': raw_name,
            'Base Name': base_name,
            'Closing Units': qty,
            'Quarterly Dividend': quarterly_div,
            'Current Cumulative': curr_cum_div,
            'Previous Cumulative': prev_div_map.get(base_name, 0.0) if prev_div_map else 0.0,
            'Is Bonus': is_bonus
        })

    df_result = pd.DataFrame(result_data)
    logging.info(f"Parsed {len(df_result)} rows from Client Working (v2).")
    return df_result
