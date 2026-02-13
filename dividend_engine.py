import pandas as pd
from fuzzywuzzy import fuzz
import logging

def verify_audit(portfolio_df, client_df, corporate_actions_df):
    """
    Performs the 3-Step Audit Verification.

    Step 1: Closing Units Reconciliation (Client vs Portfolio)
    Step 2: Dividend Verification (Expected vs Client Quarterly Increase)
    Step 3: Bonus Verification (Client Existence vs Corp Action)

    Args:
        portfolio_df: DataFrame (ISIN, Script Name, Closing Quantity)
        client_df: DataFrame (ISIN, Investment Name, Base Name, Closing Units, Quarterly Dividend, Is Bonus, Current Cumulative, Previous Cumulative)
        corporate_actions_df: DataFrame (Security Name, Ex Date, Purpose, DPS)

    Returns:
        tuple: (reconciliation_df, dividend_df, bonus_df, exception_df)
    """
    logging.info("Starting Audit Verification (v2).")

    reconciliation_data = []
    dividend_data = []
    bonus_data = []
    exception_data = []

    # Pre-process Portfolio for easier matching
    # Map: Cleaned Portfolio Script Name -> Row
    port_list = portfolio_df.to_dict('records')
    # Map: ISIN -> Row
    port_isin_map = {row['ISIN']: row for row in port_list if pd.notna(row['ISIN']) and str(row['ISIN']).strip() != ""}

    # Pre-process Corp Actions for easier matching
    # Map: Cleaned Security Name -> List of Actions
    corp_list = corporate_actions_df.to_dict('records')

    matched_port_indices = set()

    # ==========================================
    # GROUP CLIENT DATA BY ISIN / BASE NAME
    # ==========================================
    # We reconcile on AGGREGATED Holdings.
    # Priority for grouping: ISIN. If missing, fallback to Base Name.

    def get_group_key(row):
        isin = str(row['ISIN']).strip()
        if isin and isin.upper() != "NAN" and isin != "":
            return isin
        return "NAME:" + str(row['Base Name']).strip().upper()

    # Create a temporary column for grouping
    client_df = client_df.copy()
    client_df['GroupKey'] = client_df.apply(get_group_key, axis=1)

    # Aggregation
    client_grouped = client_df.groupby('GroupKey').agg({
        'ISIN': 'first',
        'Base Name': 'first',
        'Closing Units': 'sum',
        'Quarterly Dividend': 'sum',
        'Is Bonus': lambda x: any(x), # True if any row is bonus
        'Investment Name': list # Keep list of original names
    }).reset_index()

    # ==========================================
    # STEP 1: CLOSING UNITS RECONCILIATION
    # ==========================================

    for _, group_row in client_grouped.iterrows():
        isin = group_row['ISIN']
        # Clean ISIN
        if pd.isna(isin) or str(isin).strip() == "" or str(isin).lower() == "nan":
            isin = None

        base_name = group_row['Base Name']
        total_client_units = group_row['Closing Units']
        total_q_div = group_row['Quarterly Dividend']
        has_bonus = group_row['Is Bonus']
        original_names = group_row['Investment Name']

        # --- Match with Portfolio ---
        port_match = None
        match_type = "None"
        best_port_score = 0

        # 1. Try Exact ISIN Match
        if isin:
            if isin in port_isin_map:
                port_match = port_isin_map[isin]
                match_type = "ISIN"
                best_port_score = 100 # Exact match
            else:
                match_type = "ISIN (Not Found)"

        # 2. If no ISIN (or ISIN lookup failed? No, if ISIN failed we respect it), try Name Match ONLY if ISIN missing
        # Wait, if ISIN is present but not in Portfolio, it means Portfolio doesn't have it.
        # We should NOT try to match by name in that case, because ISIN is unique identifier.
        # Unless the user entered wrong ISIN? But we assume data integrity.
        # So only try name match if ISIN was None.

        if not isin and not port_match:
             for idx, port_row in enumerate(port_list):
                score = fuzz.token_sort_ratio(str(base_name).lower(), str(port_row['Script Name']).lower())
                if score > best_port_score:
                    best_port_score = score
                    # Threshold 80%
                    if score >= 80:
                        port_match = port_row
                        match_type = "Fuzzy Name"

        # Prepare Report Variables
        port_units = 0.0
        port_script = "Not Found"
        match_status = "No Match"

        if port_match:
            port_units = port_match['Closing Quantity']
            port_script = port_match['Script Name']

            diff_units = total_client_units - port_units
            if diff_units == 0:
                match_status = "Matched"
            else:
                match_status = "Mismatch"
                exception_data.append({
                    'Investment': base_name,
                    'Issue': 'Quantity Mismatch',
                    'Details': f"Match by {match_type}. Client: {total_client_units}, Port: {port_units}"
                })
        else:
            match_status = "Not Found in Portfolio"
            diff_units = total_client_units
            if total_client_units > 0:
                 exception_data.append({
                    'Investment': base_name,
                    'Issue': 'Portfolio Missing',
                    'Details': f"Lookup by {match_type}. ISIN: {isin if isin else 'N/A'}"
                })

        # Add to Reconciliation Report
        reconciliation_data.append({
            'ISIN': isin if isin else "",
            'Investment (Client)': base_name,
            'Script Name (Port)': port_script,
            'Client Units': total_client_units,
            'Portfolio Units': port_units,
            'Difference': diff_units,
            'Status': match_status,
            'Match Method': match_type
        })

        # ==========================================
        # STEP 2: DIVIDEND VERIFICATION
        # ==========================================

        # Find matching Corporate Action (Dividend)
        # We use Portfolio Name if available (it's official), else Client Base Name
        search_name = port_script if port_match else base_name

        matched_dps = 0.0

        for ca_row in corp_list:
            if "dividend" in str(ca_row['Purpose']).lower():
                score = fuzz.token_sort_ratio(str(search_name).lower(), str(ca_row['Security Name']).lower())
                if score >= 80:
                    dps = ca_row.get('DPS')
                    if dps is not None and not pd.isna(dps):
                        matched_dps += float(dps)

        # Calculate Expected
        # Expected = DPS * Portfolio Closing Units (if matched)
        # Use Portfolio units if we have a match, otherwise 0 (can't verify)
        calc_units = port_units if match_status != "No Match" else 0
        expected_div = matched_dps * calc_units

        div_diff = total_q_div - expected_div

        # Report if Relevant
        if expected_div > 0 or total_q_div > 0:
            div_status = "Matched" if abs(div_diff) < 1.0 else "Mismatch"

            if div_status == "Mismatch":
                 exception_data.append({
                    'Investment': base_name,
                    'Issue': 'Dividend Mismatch',
                    'Details': f"Client: {total_q_div}, Expected: {expected_div} (DPS: {matched_dps}, Units: {calc_units})"
                })

            dividend_data.append({
                'ISIN': isin if isin else "",
                'Investment': base_name,
                'DPS (Corp)': matched_dps,
                'Units (Port)': calc_units,
                'Expected Dividend': expected_div,
                'Client Increase': total_q_div,
                'Difference': div_diff,
                'Status': div_status
            })

    # ==========================================
    # STEP 3: BONUS VERIFICATION
    # ==========================================

    for _, group_row in client_grouped.iterrows():
        base_name = group_row['Base Name']
        isin = group_row['ISIN']
        has_client_bonus = group_row['Is Bonus']

        # Use Portfolio script name if available (more accurate for matching Corp Actions)
        # We need to re-find the match (or store it earlier)
        # For simplicity, let's re-use the search_name logic or just Base Name
        # Actually, using Base Name is safer if we didn't find Portfolio match.
        # But if we found Portfolio match by ISIN, we should use that name.
        # Let's quickly re-lookup
        port_match = port_isin_map.get(isin) if isin and isin in port_isin_map else None
        search_name = port_match['Script Name'] if port_match else base_name

        # Check Corp Action for Bonus
        has_corp_bonus = False
        corp_bonus_details = ""

        for ca_row in corp_list:
            if "bonus" in str(ca_row['Purpose']).lower():
                score = fuzz.token_sort_ratio(str(search_name).lower(), str(ca_row['Security Name']).lower())
                if score >= 80:
                    has_corp_bonus = True
                    corp_bonus_details = ca_row['Purpose']
                    break

        status = "OK"
        if has_client_bonus and not has_corp_bonus:
            status = "Client has Bonus, Corp Action Missing"
            exception_data.append({
                'Investment': base_name,
                'Issue': 'Bonus Verification Failed',
                'Details': 'Client shows bonus, no corporate action found.'
            })
        elif has_corp_bonus and not has_client_bonus:
            status = "Corp Action has Bonus, Client Missing"
            exception_data.append({
                'Investment': base_name,
                'Issue': 'Bonus Verification Failed',
                'Details': f"Corporate action ({corp_bonus_details}), client missing bonus row."
            })

        if has_client_bonus or has_corp_bonus:
            bonus_data.append({
                'ISIN': isin if isin else "",
                'Investment': base_name,
                'Bonus in Corp Action': "Yes" if has_corp_bonus else "No",
                'Bonus in Working': "Yes" if has_client_bonus else "No",
                'Status': status
            })

    return (pd.DataFrame(reconciliation_data),
            pd.DataFrame(dividend_data),
            pd.DataFrame(bonus_data),
            pd.DataFrame(exception_data))
