import pandas as pd
from fuzzywuzzy import fuzz
import logging

def calculate_dividends(working_file_df, corporate_actions_df):
    """
    Calculates expected dividends by matching Working File Script Codes with Corporate Action Security Codes.

    Args:
        working_file_df (pd.DataFrame): DataFrame from parse_working_file (Script Code, Script Name, Quantity).
        corporate_actions_df (pd.DataFrame): DataFrame from process_corporate_actions.

    Returns:
        tuple: (dividend_df, exception_df)
    """
    logging.info("Starting dividend calculation using Working File.")

    dividend_data = []
    exception_data = []

    if working_file_df.empty:
        return pd.DataFrame(), pd.DataFrame([{'Issue': 'Working File Empty', 'Details': 'No data in Excel'}])

    # Create a lookup dictionary for Working File: Script Code -> Row Data
    # Script Code is int
    wf_map = working_file_df.set_index('Script Code').to_dict('index')

    # Track which Working File entries matched a dividend (for coverage check if needed, though usually not required for Divs)
    matched_wf_codes = set()

    if not corporate_actions_df.empty:
        for _, ca_row in corporate_actions_df.iterrows():
            # Get data from Corporate Action
            ca_code = ca_row.get('Security Code')
            ca_name = ca_row.get('Security Name')
            ca_purpose = ca_row.get('Purpose', '')
            ca_ex_date = ca_row.get('Ex Date')
            ca_dps = ca_row.get('DPS')

            # Ensure ca_code is int if possible
            try:
                ca_code = int(ca_code)
            except (ValueError, TypeError):
                exception_data.append({
                    'Script Code': ca_code,
                    'Script Name': ca_name,
                    'Issue': 'Invalid Security Code',
                    'Details': 'Code in Corporate Action is not a valid number'
                })
                continue

            # Check for Bonus (Audit Requirement)
            if "bonus" in str(ca_purpose).lower():
                # Check if Working File has this script
                if ca_code in wf_map:
                    wf_row = wf_map[ca_code]
                    wf_details = wf_row.get('Details', '')
                    if "bonus" not in wf_details.lower():
                        exception_data.append({
                            'Script Code': ca_code,
                            'Script Name': wf_row['Script Name'],
                            'Issue': 'Bonus Mismatch',
                            'Details': f"Bonus declared ({ca_purpose}) but 'Bonus' not found in Working File details: {wf_details}"
                        })
                else:
                     exception_data.append({
                        'Script Code': ca_code,
                        'Script Name': ca_name,
                        'Issue': 'Bonus Declared - No Holding',
                        'Details': f"Bonus declared ({ca_purpose}) but no holding found in Working File"
                    })

            # Check for Dividend
            if "dividend" in str(ca_purpose).lower():
                # Try to find match in Working File
                if ca_code in wf_map:
                    wf_row = wf_map[ca_code]
                    matched_wf_codes.add(ca_code)

                    qty = wf_row['Quantity']
                    script_name = wf_row['Script Name']

                    if pd.isna(ca_dps):
                         exception_data.append({
                            'Script Code': ca_code,
                            'Script Name': script_name,
                            'Issue': 'DPS Extraction Failed',
                            'Details': f"Purpose: {ca_purpose}"
                        })
                    else:
                        expected_div = qty * ca_dps
                        dividend_data.append({
                            'Script Code': ca_code,
                            'Script Name': script_name,
                            'Ex Date': ca_ex_date,
                            'DPS': ca_dps,
                            'Quantity': qty,
                            'Expected Dividend': expected_div,
                            'Remarks': ca_purpose
                        })
                else:
                    # Dividend declared but no holding
                     exception_data.append({
                        'Script Code': ca_code,
                        'Script Name': ca_name,
                        'Issue': 'Dividend Declared - No Holding',
                        'Details': f"Purpose: {ca_purpose}"
                    })

    dividend_df = pd.DataFrame(dividend_data)
    exception_df = pd.DataFrame(exception_data)

    return dividend_df, exception_df


def reconcile_holdings(portfolio_df, working_file_df, fuzzy_threshold=80):
    """
    Reconciles Closing Quantity between Portfolio HTML (NSDL) and Working File (Excel).
    Uses Fuzzy Matching on Script Name.

    Args:
        portfolio_df (pd.DataFrame): NSDL HTML data (ISIN, Script Name, Closing Quantity).
        working_file_df (pd.DataFrame): Working File data (Script Code, Script Name, Quantity).
        fuzzy_threshold (int): Match score threshold.

    Returns:
        pd.DataFrame: Reconciliation Report.
    """
    logging.info("Starting holdings reconciliation.")

    reconciliation_data = []

    # Track matched portfolio indices to find what's missing in Working File
    matched_port_indices = set()

    # Working File List
    wf_list = working_file_df.to_dict('records')

    # 1. Check Working File against Portfolio
    for wf_row in wf_list:
        wf_name = wf_row['Script Name']
        wf_qty = wf_row['Quantity']
        wf_code = wf_row['Script Code']

        best_match_idx = -1
        best_score = 0

        for idx, port_row in portfolio_df.iterrows():
            port_name = port_row['Script Name']
            score = fuzz.token_sort_ratio(str(wf_name).lower(), str(port_name).lower())

            if score > best_score:
                best_score = score
                best_match_idx = idx

        status = "Mismatch"
        diff = 0
        port_qty = 0
        port_isin = "N/A"
        port_name_found = "N/A"

        if best_score >= fuzzy_threshold and best_match_idx != -1:
            matched_port_indices.add(best_match_idx)
            best_match = portfolio_df.loc[best_match_idx]

            port_qty = best_match['Closing Quantity']
            port_isin = best_match['ISIN']
            port_name_found = best_match['Script Name']

            diff = wf_qty - port_qty
            if diff == 0:
                status = "Matched"
            else:
                status = "Quantity Mismatch"
        else:
            status = "Not Found in Portfolio"
            diff = wf_qty # Excess in WF

        reconciliation_data.append({
            'Script Code (WF)': wf_code,
            'Script Name (WF)': wf_name,
            'Quantity (WF)': wf_qty,
            'ISIN (Port)': port_isin,
            'Script Name (Port)': port_name_found,
            'Quantity (Port)': port_qty,
            'Difference': diff,
            'Status': status,
            'Match Score': best_score
        })

    # 2. Check Portfolio entries NOT matched in Working File
    for idx, port_row in portfolio_df.iterrows():
        if idx not in matched_port_indices:
            reconciliation_data.append({
                'Script Code (WF)': 'N/A',
                'Script Name (WF)': 'N/A',
                'Quantity (WF)': 0,
                'ISIN (Port)': port_row['ISIN'],
                'Script Name (Port)': port_row['Script Name'],
                'Quantity (Port)': port_row['Closing Quantity'],
                'Difference': -port_row['Closing Quantity'],
                'Status': "Not Found in Working File",
                'Match Score': 0
            })

    return pd.DataFrame(reconciliation_data)
