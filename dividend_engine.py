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
        client_df: DataFrame (Investment Name, Base Name, Closing Units, Quarterly Dividend, Is Bonus, Current Cumulative, Previous Cumulative)
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

    # Pre-process Corp Actions for easier matching
    # Map: Cleaned Security Name -> List of Actions
    corp_list = corporate_actions_df.to_dict('records')

    matched_port_indices = set()

    # ==========================================
    # GROUP CLIENT DATA BY BASE NAME
    # ==========================================
    # We reconcile on AGGREGATED Holdings, but keep Dividend info

    # Aggregation
    client_grouped = client_df.groupby('Base Name').agg({
        'Closing Units': 'sum',
        'Quarterly Dividend': 'sum',
        'Is Bonus': lambda x: any(x), # True if any row is bonus
        'Investment Name': list # Keep list of original names
    }).reset_index()

    # ==========================================
    # STEP 1: CLOSING UNITS RECONCILIATION
    # ==========================================

    for _, group_row in client_grouped.iterrows():
        base_name = group_row['Base Name']
        total_client_units = group_row['Closing Units']
        total_q_div = group_row['Quarterly Dividend']
        has_bonus = group_row['Is Bonus']
        original_names = group_row['Investment Name']

        # --- Match with Portfolio ---
        best_port_match = None
        best_port_score = 0
        best_port_idx = -1

        for idx, port_row in enumerate(port_list):
            score = fuzz.token_sort_ratio(str(base_name).lower(), str(port_row['Script Name']).lower())
            if score > best_port_score:
                best_port_score = score
                best_port_match = port_row
                best_port_idx = idx

        # Threshold 80%
        port_units = 0.0
        port_script = "Not Found"
        match_status = "No Match"

        if best_port_score >= 80 and best_port_match:
            port_units = best_port_match['Closing Quantity']
            port_script = best_port_match['Script Name']
            matched_port_indices.add(best_port_idx)

            diff_units = total_client_units - port_units
            if diff_units == 0:
                match_status = "Matched"
            else:
                match_status = "Mismatch"
                exception_data.append({
                    'Investment': base_name,
                    'Issue': 'Quantity Mismatch',
                    'Details': f"Client Total: {total_client_units}, Portfolio: {port_units}"
                })
        else:
            match_status = "Not Found in Portfolio"
            diff_units = total_client_units
            if total_client_units > 0:
                 exception_data.append({
                    'Investment': base_name,
                    'Issue': 'Portfolio Missing',
                    'Details': f"Best match: {best_port_score}% ({port_script if best_port_match else 'None'})"
                })

        # Add to Reconciliation Report
        reconciliation_data.append({
            'Investment (Client)': base_name, # Grouped Name
            'Script Name (Port)': port_script,
            'Client Units': total_client_units,
            'Portfolio Units': port_units,
            'Difference': diff_units,
            'Status': match_status,
            'Match Score': best_port_score
        })

        # ==========================================
        # STEP 2: DIVIDEND VERIFICATION
        # ==========================================

        # Find matching Corporate Action (Dividend)
        # Ideally use Portfolio Name if matched, else Client Base Name
        search_name = port_script if best_port_score >= 80 else base_name

        matched_dps = 0.0

        for ca_row in corp_list:
            if "dividend" in str(ca_row['Purpose']).lower():
                score = fuzz.token_sort_ratio(str(search_name).lower(), str(ca_row['Security Name']).lower())
                if score >= 80:
                    dps = ca_row.get('DPS')
                    if dps is not None and not pd.isna(dps):
                        matched_dps += float(dps)

        # Calculate Expected
        # Expected = DPS * Portfolio Closing Units
        # Using Portfolio Units (reconciled/audit standard)
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
        has_client_bonus = group_row['Is Bonus']

        # Check Corp Action for Bonus
        has_corp_bonus = False
        corp_bonus_details = ""

        for ca_row in corp_list:
            if "bonus" in str(ca_row['Purpose']).lower():
                score = fuzz.token_sort_ratio(str(base_name).lower(), str(ca_row['Security Name']).lower())
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
                'Investment': base_name,
                'Bonus in Corp Action': "Yes" if has_corp_bonus else "No",
                'Bonus in Working': "Yes" if has_client_bonus else "No",
                'Status': status
            })

    return (pd.DataFrame(reconciliation_data),
            pd.DataFrame(dividend_data),
            pd.DataFrame(bonus_data),
            pd.DataFrame(exception_data))
