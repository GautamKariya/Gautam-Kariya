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

    Raises:
        ValueError: If parsing fails (sheet not found, header not found, columns missing).
    """
    logging.info("Starting Client Working File parsing (v2).")

    def load_shares_sheet(f, file_label="Current File"):
        xls = None
        try:
            # Try to let Pandas auto-detect engine
            # This handles .xlsx (openpyxl) and .xls (xlrd) automatically if libraries are installed.
            # Streamlit file uploader returns a BytesIO which pandas reads.
            # However, sometimes if extension is missing/wrong, we might need to hint.
            # Let's try default first.
            xls = pd.ExcelFile(f)
        except Exception as e:
            # If default fails, maybe try explicit openpyxl if it was a zip error
            # But usually pandas tries both.
            # If it's "File is not a zip file", it means it tried openpyxl on a non-zip file (like .xls).
            # If xlrd is installed, pandas *should* fall back to it for .xls signatures.
            # If it failed, it means either:
            # 1. It's not a valid Excel file at all.
            # 2. It's an .xls file but pandas tried openpyxl first and gave up.
            # Let's try explicit xlrd as fallback.
            try:
                f.seek(0)
                xls = pd.ExcelFile(f, engine='xlrd')
            except Exception as e2:
                logging.error(f"Error reading Excel {file_label}: {e}")
                raise ValueError(f"Failed to read Excel file {file_label}. Please ensure it is a valid .xlsx or .xls file. Error: {str(e)}")

        try:
            # Case-insensitive sheet search
            sheet_name = None
            for name in xls.sheet_names:
                if "SHARES" in name.upper():
                    sheet_name = name
                    break

            if not sheet_name:
                raise ValueError(f"Sheet 'SHARES' not found in {file_label}. Available sheets: {xls.sheet_names}")

            # Read first 50 rows to find header
            # Note: We need to handle merged cells or empty cells in header row carefully.
            # Ideally, we read as string to preserve content.
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=50)

            header_idx = None
            for i, row in df.iterrows():
                # Join row values to string for keyword search
                # Handle NaNs and non-string types
                row_str = " ".join([str(x) for x in row if pd.notna(x)]).lower()

                # Keywords: "Name of Investment" AND ("Closing" OR "Opening") AND "units"
                # More robust: "Name" AND "Investment" AND ("Closing" OR "Opening")
                if "name" in row_str and "investment" in row_str and ("closing" in row_str or "opening" in row_str):
                    header_idx = i
                    break

            if header_idx is None:
                raise ValueError(f"Header row not found in '{sheet_name}' sheet within first 50 rows (checked for 'Name', 'Investment', 'Closing/Opening').")

            # Reload with correct header
            df = pd.read_excel(xls, sheet_name=sheet_name, header=header_idx)
            return df

        except ValueError as ve:
            logging.error(f"Validation Error in {file_label}: {ve}")
            raise ve
        except Exception as e:
            logging.error(f"Error processing sheet in {file_label}: {e}")
            raise ValueError(f"Failed to process sheet content in {file_label}: {str(e)}")

    # Load Current
    df_curr = load_shares_sheet(file, "Current Quarter Client Working")
    if df_curr.empty:
        raise ValueError("Parsed 'Shares' sheet is empty.")

    # Load Previous (if exists)
    df_prev = pd.DataFrame()
    if previous_file:
        try:
            df_prev = load_shares_sheet(previous_file, "Previous Quarter Client Working")
        except ValueError as ve:
            logging.warning(f"Previous file parsing failed: {ve}. Proceeding without previous data.")
            pass

    def find_columns(df):
        name_col = None
        qty_col = None
        div_col = None
        isin_col = None

        # We search column headers
        # Headers might contain newlines if read directly from Excel, usually Pandas keeps them.
        for col in df.columns:
            c_str = str(col).lower()

            # Name Column
            if "name" in c_str and "investment" in c_str:
                name_col = col
                continue

            # ISIN Column (New Requirement)
            if "isin" in c_str: # Matches "ISIN CODE"
                isin_col = col
                continue

            # Quantity Column (Closing Units)
            # Must contain "Closing" AND "units"
            if "closing" in c_str and "units" in c_str:
                qty_col = col
                continue

            # Dividend Column
            # Contains "DIVIDEND" (more specific than "DIV") but NOT "BONUS"
            if "dividend" in c_str and "bonus" not in c_str:
                div_col = col
                continue

        return name_col, isin_col, qty_col, div_col

    # Identify Columns in Current
    name_col, isin_col, qty_col, div_col = find_columns(df_curr)

    if not all([name_col, isin_col, qty_col, div_col]):
        missing = []
        if not name_col: missing.append("Name of Investment")
        if not isin_col: missing.append("ISIN CODE")
        if not qty_col: missing.append("Closing Units")
        if not div_col: missing.append("Dividend")
        error_msg = f"Missing required columns in Current File: {', '.join(missing)}"
        logging.error(error_msg)
        raise ValueError(error_msg)

    # Process Data
    result_data = []

    # Create a map of Previous Cumulative Dividends if available
    prev_div_map = {}
    if not df_prev.empty:
        # Note: Previous file might not have ISIN column if it's old format.
        # So we should be careful. But for dividend calc, we match on Base Name currently.
        # If we switch to matching on ISIN for Dividends too, we need ISIN in prev file.
        # However, the user said they added ISIN column to "Client Working File".
        # Assuming current and future files have it. Previous files might not.
        # Let's try to extract ISIN from prev file if available, otherwise use Base Name map as fallback?
        # The logic below uses Base Name as key for `prev_div_map`.
        # Since the ISIN matching is primarily for Portfolio <-> Client reconciliation,
        # and Dividend Diff is calculated per Client row (or group),
        # we can stick to Base Name for the Dividend Carry Forward logic WITHIN the Client file (Current vs Prev).
        # Unless ISIN is better. Base Name is unique enough usually.
        # Let's keep Base Name for prev_div_map key for now to support backward compatibility if prev file lacks ISIN.

        p_name_col, _, p_qty_col, p_div_col = find_columns(df_prev)

        if p_name_col and p_div_col:
            for _, row in df_prev.iterrows():
                raw_name = str(row[p_name_col])
                if pd.isna(raw_name) or raw_name.strip() == "":
                    continue
                # Clean name to get Base Name
                base_name = raw_name.upper().replace("(BONUS)", "").strip()
                try:
                    val = float(row[p_div_col])
                    if base_name not in prev_div_map:
                         prev_div_map[base_name] = val
                    else:
                        prev_div_map[base_name] = max(prev_div_map[base_name], val)
                except (ValueError, TypeError):
                    pass

    for _, row in df_curr.iterrows():
        raw_name = str(row[name_col])

        # Row Filtering Logic
        if pd.isna(raw_name) or raw_name.strip() == "":
            continue

        # Ignore "Total" rows
        if "total" in raw_name.lower():
            continue

        # 1. Base Name Logic
        base_name = raw_name.upper().replace("(BONUS)", "").strip()
        is_bonus = "(BONUS)" in raw_name.upper()

        # Extract ISIN
        isin_val = str(row[isin_col]).strip().upper() if pd.notna(row[isin_col]) else ""

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
        quarterly_div = 0.0

        if curr_cum_div > 0:
            # Match with previous based on Base Name (as ISIN might be missing in prev file)
            prev_cum_div = prev_div_map.get(base_name, 0.0)
            quarterly_div = curr_cum_div - prev_cum_div

        result_data.append({
            'ISIN': isin_val,
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
