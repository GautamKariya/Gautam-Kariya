import pandas as pd
from fuzzywuzzy import fuzz
import logging

def calculate_dividends(portfolio_df, corporate_actions_df, fuzzy_threshold=80):
    """
    Matches portfolio ISINs with corporate actions and calculates expected dividends.

    Args:
        portfolio_df (pd.DataFrame): DataFrame from parse_portfolio_html.
        corporate_actions_df (pd.DataFrame): DataFrame from process_corporate_actions.
        fuzzy_threshold (int): The threshold for fuzzy matching.

    Returns:
        tuple: (dividend_working_df, exception_report_df)
    """
    logging.info("Starting dividend calculation.")

    dividend_working_data = []
    exception_data = []

    if portfolio_df.empty:
        logging.warning("Portfolio is empty.")
        return pd.DataFrame(), pd.DataFrame([{'Issue': 'Portfolio Empty', 'Details': 'No holdings found'}])

    matched_portfolio_indices = set()

    # Iterate over corporate actions to find matches in portfolio
    if not corporate_actions_df.empty:
        for _, ca_row in corporate_actions_df.iterrows():
            ca_security_name = ca_row.get('Security Name', '')
            ca_dps = ca_row.get('DPS')
            ca_ex_date = ca_row.get('Ex Date')
            ca_purpose = ca_row.get('Purpose')

            best_match_score = 0
            best_match_idx = None

            # Find best match in portfolio
            for idx, port_row in portfolio_df.iterrows():
                port_script_name = port_row['Script Name']
                score = fuzz.token_sort_ratio(str(ca_security_name).lower(), str(port_script_name).lower())

                if score > best_match_score:
                    best_match_score = score
                    best_match_idx = idx

            # Check if match is good enough
            if best_match_score >= fuzzy_threshold and best_match_idx is not None:
                matched_portfolio_indices.add(best_match_idx)
                port_row = portfolio_df.loc[best_match_idx]

                best_match_isin = port_row['ISIN']
                best_match_name = port_row['Script Name']
                best_match_qty = port_row['Closing Quantity']

                if pd.isna(ca_dps):
                    exception_data.append({
                        'ISIN': best_match_isin,
                        'Script': best_match_name,
                        'Issue': 'DPS Extraction Failed',
                        'Details': f"Could not extract DPS from: {ca_purpose}"
                    })
                else:
                    expected_dividend = best_match_qty * ca_dps

                    if best_match_qty < 0:
                        exception_data.append({
                            'ISIN': best_match_isin,
                            'Script': best_match_name,
                            'Issue': 'Negative Quantity',
                            'Details': f"Quantity is {best_match_qty}"
                        })

                    dividend_working_data.append({
                        'ISIN': best_match_isin,
                        'Script': best_match_name,
                        'Ex Date': ca_ex_date,
                        'DPS': ca_dps,
                        'Qty': best_match_qty,
                        'Expected Dividend': expected_dividend
                    })
            else:
                exception_data.append({
                    'ISIN': 'No Match',
                    'Script': ca_security_name,
                    'Issue': 'Dividend Declared but No Holding Match',
                    'Details': f"Best match score: {best_match_score}"
                })

    # Now check for "Holding exists but dividend not declared"
    for idx, port_row in portfolio_df.iterrows():
        if idx not in matched_portfolio_indices:
            exception_data.append({
                'ISIN': port_row['ISIN'],
                'Script': port_row['Script Name'],
                'Issue': 'No Dividend Declared',
                'Details': 'No matching corporate action found for this quarter'
            })

    dividend_df = pd.DataFrame(dividend_working_data)
    exception_df = pd.DataFrame(exception_data)

    logging.info(f"Calculated {len(dividend_df)} dividend records and {len(exception_df)} exceptions.")
    return dividend_df, exception_df
