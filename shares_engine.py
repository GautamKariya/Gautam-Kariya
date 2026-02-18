import pandas as pd
import numpy as np
from io import BytesIO

def run_verification(shares_df, portfolio_df, corp_action_df, bhav_copy_df):
    """
    Runs the verification logic.
    Returns:
        summary_stats (dict): Counts of mismatches.
        detailed_report (dict of DataFrames): Sheets for Excel.
        exceptions_df (DataFrame): Consolidated exceptions.
    """

    # Initialize results
    results = []
    exceptions = []

    # Group Corporate Actions by Script Code
    # Sum DPS for Dividend
    # Sum Bonus Ratio for Bonus? No, Bonus is event specific.
    # But usually one bonus per period. If multiple, we should handle.
    # User said: "Expected Bonus Units = Opening Units * (B/A)".
    # If multiple bonuses? Rare. But let's assume we sum the expected units from each event.

    # Pre-process Corporate Actions
    # Create a dictionary for fast lookup
    corp_actions = {}
    if corp_action_df is not None and not corp_action_df.empty:
        for script_code, group in corp_action_df.groupby('script_code'):
            bonuses = group[group['action_type'] == 'Bonus']
            dividends = group[group['action_type'] == 'Dividend']

            corp_actions[script_code] = {
                'bonus_ratios': bonuses['value'].tolist(), # List of ratios
                'total_dps': dividends['value'].sum()
            }

    # Pre-process Portfolio and Bhav Copy for lookup
    portfolio_map = {}
    if portfolio_df is not None and not portfolio_df.empty:
        portfolio_map = portfolio_df.set_index('isin')['portfolio_closing_units'].to_dict()

    bhav_map = {}
    if bhav_copy_df is not None and not bhav_copy_df.empty:
        # Check if ISIN is in bhav_copy_df columns
        if 'ISIN' in bhav_copy_df.columns:
            bhav_map = bhav_copy_df.set_index('ISIN')['bhav_close'].to_dict()
        elif 'isin' in bhav_copy_df.columns: # lowercase check
            bhav_map = bhav_copy_df.set_index('isin')['bhav_close'].to_dict()

    # Iterate through Shares Input
    # We need to perform all verifications row by row

    detailed_data = []

    for idx, row in shares_df.iterrows():
        isin = row.get('isin')
        script_code = row.get('script_code')
        name = row.get('name', '')

        # Inputs
        opening_units = row.get('opening_units', 0.0)
        input_bonus = row.get('bonus_recd', 0.0)
        input_closing_units = row.get('closing_units', 0.0)
        input_closing_amount = row.get('closing_amount', 0.0)
        input_market_price = row.get('market_price', 0.0)
        input_market_value = row.get('market_value', 0.0)
        input_ugl = row.get('ugl', 0.0)
        input_dividend = row.get('dividend_recd', 0.0)

        # 1. Closing Units Verification
        portfolio_units = portfolio_map.get(isin, 0.0) if isin else 0.0
        # If ISIN not in portfolio, maybe it's 0 balance?
        # But if Input says 100 and Portfolio has no record, Portfolio Units = 0.
        # Mismatch = Input - Portfolio

        closing_match = abs(input_closing_units - portfolio_units) < 0.01

        # 2. Bonus Verification
        # Look up corporate actions
        ca = corp_actions.get(script_code, {'bonus_ratios': [], 'total_dps': 0.0})

        expected_bonus = 0.0
        for ratio in ca['bonus_ratios']:
            expected_bonus += opening_units * ratio

        bonus_match = abs(input_bonus - expected_bonus) < 0.01

        # 3. Dividend Verification
        total_dps = ca['total_dps']
        expected_dividend = input_closing_units * total_dps

        dividend_match = abs(input_dividend - expected_dividend) < 1.0 # Allow small rounding diff for currency

        # 4. Market Price Verification
        bhav_price = bhav_map.get(isin, 0.0) if isin else 0.0
        # If not found in Bhav Copy, price is 0 (or Exception?)
        # If input price is > 0 and bhav is 0, mismatch.

        price_match = abs(input_market_price - bhav_price) < 0.05 # Allow small tick diff

        # 5. Market Value Verification
        # Expected MV = Closing Units * Market Price
        # Which Market Price? Input Market Price or Bhav Copy?
        # Requirement: "Expected MV = Closing Units * Market Price. Compare with Input MV."
        # Usually internal consistency check uses Input Market Price.
        # But for full audit, we should use Bhav Price.
        # However, the requirement lists Market Value separately from Market Price.
        # "Market Value Verification: Expected MV = Closing Units * Market Price. Compare with Input MV."
        # If Market Price Verification failed, MV Verification might also fail if we use Bhav Price.
        # Standard Audit: Verify Price first. Then Verify MV using Input Price (Math check) OR Bhav Price (Valuation check).
        # Given "Expected MV = Closing Units * Market Price", I'll use the Bhav Price as it's the source of truth for "Market Price".
        # Wait, if I use Input Price, I'm just checking Excel math.
        # If I use Bhav Price, I'm verifying the valuation.
        # Re-reading: "Market Price Verification: Compare Input Market Price vs Bhav CLOSE. Mismatch -> Exception."
        # "Market Value Verification: Expected MV = Closing Units * Market Price. Compare with Input MV."
        # It's ambiguous which "Market Price" to use.
        # But since we have a separate Exception for Price, I will use the Bhav Price for MV calculation to be stricter.
        # If Price is wrong, MV is wrong.
        # If Price is right, MV might still be wrong (math error).
        # I'll use Bhav Price.

        expected_mv = input_closing_units * bhav_price
        mv_match = abs(input_market_value - expected_mv) < 1.0

        # 6. UGL Verification
        # Expected UGL = Market Value - Closing Amount
        # Using Expected MV (calculated from Bhav) or Input MV?
        # Again, stricter to use Expected MV.

        expected_ugl = expected_mv - input_closing_amount
        ugl_match = abs(input_ugl - expected_ugl) < 1.0

        # Collect Data
        record = {
            'Script Code': script_code,
            'ISIN': isin,
            'Name': name,

            # Closing Units
            'Input Closing Units': input_closing_units,
            'Portfolio Closing Units': portfolio_units,
            'Closing Units Diff': input_closing_units - portfolio_units,
            'Closing Match': closing_match,

            # Bonus
            'Opening Units': opening_units,
            'Bonus Ratios': str(ca['bonus_ratios']),
            'Input Bonus': input_bonus,
            'Expected Bonus': expected_bonus,
            'Bonus Diff': input_bonus - expected_bonus,
            'Bonus Match': bonus_match,

            # Dividend
            'Input Dividend': input_dividend,
            'Total DPS': total_dps,
            'Expected Dividend': expected_dividend,
            'Dividend Diff': input_dividend - expected_dividend,
            'Dividend Match': dividend_match,

            # Market Price
            'Input Price': input_market_price,
            'Bhav Price': bhav_price,
            'Price Diff': input_market_price - bhav_price,
            'Price Match': price_match,

            # Market Value
            'Input MV': input_market_value,
            'Expected MV': expected_mv,
            'MV Diff': input_market_value - expected_mv,
            'MV Match': mv_match,

            # UGL
            'Input UGL': input_ugl,
            'Expected UGL': expected_ugl,
            'UGL Diff': input_ugl - expected_ugl,
            'UGL Match': ugl_match
        }

        detailed_data.append(record)

        # Exceptions
        if not closing_match:
            exceptions.append({'ISIN': isin, 'Script': script_code, 'Issue': 'Closing Units Mismatch', 'Details': f"Input: {input_closing_units}, Portfolio: {portfolio_units}"})
        if not bonus_match:
            exceptions.append({'ISIN': isin, 'Script': script_code, 'Issue': 'Bonus Mismatch', 'Details': f"Input: {input_bonus}, Expected: {expected_bonus}"})
        if not dividend_match:
            exceptions.append({'ISIN': isin, 'Script': script_code, 'Issue': 'Dividend Mismatch', 'Details': f"Input: {input_dividend}, Expected: {expected_dividend}"})
        if not price_match:
            exceptions.append({'ISIN': isin, 'Script': script_code, 'Issue': 'Price Mismatch', 'Details': f"Input: {input_market_price}, Bhav: {bhav_price}"})
        if not mv_match:
            exceptions.append({'ISIN': isin, 'Script': script_code, 'Issue': 'Market Value Mismatch', 'Details': f"Input: {input_market_value}, Expected: {expected_mv}"})
        if not ugl_match:
            exceptions.append({'ISIN': isin, 'Script': script_code, 'Issue': 'UGL Mismatch', 'Details': f"Input: {input_ugl}, Expected: {expected_ugl}"})

    # Create DataFrames
    df_results = pd.DataFrame(detailed_data)
    df_exceptions = pd.DataFrame(exceptions)

    # Summary
    summary = {
        'Total Records': len(df_results),
        'Closing Units Mismatches': len(df_results[~df_results['Closing Match']]),
        'Bonus Mismatches': len(df_results[~df_results['Bonus Match']]),
        'Dividend Mismatches': len(df_results[~df_results['Dividend Match']]),
        'Price Mismatches': len(df_results[~df_results['Price Match']]),
        'MV Mismatches': len(df_results[~df_results['MV Match']]),
        'UGL Mismatches': len(df_results[~df_results['UGL Match']])
    }

    return summary, df_results, df_exceptions

def generate_excel_report(df_results, df_exceptions):
    """
    Generates the Excel file in memory.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # 1. Summary Sheet (Manual creation or from summary dict)
        # We'll just put the detailed sheets as requested

        # 'Closing Units Verification', 'Bonus Verification', 'Dividend Working',
        # 'Market Price Verification', 'Market Value & UGL', 'Exception Report'

        # Helper to write sheet
        def write_sheet(cols, sheet_name):
            if df_results.empty:
                pd.DataFrame(columns=cols).to_excel(writer, sheet_name=sheet_name, index=False)
            else:
                df_results[cols].to_excel(writer, sheet_name=sheet_name, index=False)

        write_sheet(['ISIN', 'Script Code', 'Name', 'Input Closing Units', 'Portfolio Closing Units', 'Closing Units Diff', 'Closing Match'], 'Closing Units Verification')
        write_sheet(['ISIN', 'Script Code', 'Name', 'Opening Units', 'Input Bonus', 'Expected Bonus', 'Bonus Diff', 'Bonus Match'], 'Bonus Verification')
        write_sheet(['ISIN', 'Script Code', 'Name', 'Input Closing Units', 'Total DPS', 'Input Dividend', 'Expected Dividend', 'Dividend Diff', 'Dividend Match'], 'Dividend Working')
        write_sheet(['ISIN', 'Script Code', 'Name', 'Input Price', 'Bhav Price', 'Price Diff', 'Price Match'], 'Market Price Verification')
        write_sheet(['ISIN', 'Script Code', 'Name', 'Input MV', 'Expected MV', 'MV Diff', 'MV Match', 'Input UGL', 'Expected UGL', 'UGL Diff', 'UGL Match'], 'Market Value & UGL')

        if not df_exceptions.empty:
            df_exceptions.to_excel(writer, sheet_name='Exception Report', index=False)
        else:
            pd.DataFrame(columns=['ISIN', 'Script', 'Issue', 'Details']).to_excel(writer, sheet_name='Exception Report', index=False)

    return output.getvalue()
