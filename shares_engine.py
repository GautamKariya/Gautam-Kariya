import pandas as pd
import numpy as np
from io import BytesIO

def run_verification(shares_df, portfolio_df, corp_action_df, bhav_copy_df):
    """
    Runs the verification logic using ISIN-level aggregation.
    Returns:
        summary_stats (dict): Counts of mismatches.
        detailed_report (dict of DataFrames): Sheets for Excel.
        exceptions_df (DataFrame): Consolidated exceptions.
    """

    detailed_data = []
    exceptions = []

    # 1. Pre-process Corporate Actions
    corp_actions = {}
    if corp_action_df is not None and not corp_action_df.empty:
        # Group by script_code
        for script_code, group in corp_action_df.groupby('script_code'):
            bonuses = group[group['action_type'] == 'Bonus']
            dividends = group[group['action_type'] == 'Dividend']

            corp_actions[script_code] = {
                'bonus_ratios': bonuses['value'].tolist(), # List of ratios
                'total_dps': dividends['value'].sum()
            }

    # 2. Pre-process Portfolio and Bhav Copy
    portfolio_map = {}
    if portfolio_df is not None and not portfolio_df.empty:
        # Portfolio is already ISIN -> Closing Units
        portfolio_map = portfolio_df.set_index('isin')['portfolio_closing_units'].to_dict()

    bhav_map = {}
    if bhav_copy_df is not None and not bhav_copy_df.empty:
        if 'ISIN' in bhav_copy_df.columns:
            bhav_map = bhav_copy_df.set_index('ISIN')['bhav_close'].to_dict()
        elif 'isin' in bhav_copy_df.columns:
            bhav_map = bhav_copy_df.set_index('isin')['bhav_close'].to_dict()

    # 3. Aggregate Shares Input by ISIN
    if shares_df is None or shares_df.empty:
        # Return valid empty structures if no input
        return {
            'Total ISINs': 0, 'Closing Units Mismatches': 0, 'Bonus Mismatches': 0,
            'Dividend Mismatches': 0, 'MV/Price Mismatches': 0
        }, pd.DataFrame(), pd.DataFrame()

    # Columns to sum
    sum_cols = ['opening_units', 'bonus_recd', 'closing_units', 'closing_amount', 'dividend_recd', 'market_value']
    # Columns to keep first (metadata)
    first_cols = ['script_code', 'name']

    # Ensure all sum_cols exist
    for col in sum_cols:
        if col not in shares_df.columns:
            shares_df[col] = 0.0

    # Group by ISIN
    agg_dict = {c: 'sum' for c in sum_cols}
    agg_dict['market_price'] = 'mean' # Average price across split rows
    for c in first_cols:
        if c in shares_df.columns:
             agg_dict[c] = 'first'

    shares_agg = shares_df.groupby('isin', as_index=False).agg(agg_dict)

    # 4. Perform Verification on Aggregated Data
    for idx, row in shares_agg.iterrows():
        isin = row['isin']
        script_code = row.get('script_code', '')
        name = row.get('name', '')

        # Aggregated Inputs
        agg_opening_units = row['opening_units']
        agg_bonus_recd = row['bonus_recd']
        agg_closing_units = row['closing_units']
        agg_closing_amount = row['closing_amount']
        agg_dividend_recd = row['dividend_recd']
        agg_market_value = row['market_value']
        input_price = row['market_price']

        # --- A. Closing Units Verification ---
        portfolio_units = portfolio_map.get(isin, 0.0)
        closing_diff = agg_closing_units - portfolio_units
        closing_match = abs(closing_diff) < 0.01

        if not closing_match:
            exceptions.append({
                'ISIN': isin, 'Script': script_code,
                'Issue': 'Closing Units Mismatch',
                'Details': f"Input: {agg_closing_units}, Portfolio: {portfolio_units}"
            })

        # --- B. Bonus Verification ---
        ca = corp_actions.get(script_code, {'bonus_ratios': [], 'total_dps': 0.0})
        expected_bonus = 0.0
        for ratio in ca['bonus_ratios']:
            expected_bonus += agg_opening_units * ratio

        bonus_diff = agg_bonus_recd - expected_bonus
        bonus_match = abs(bonus_diff) < 0.01

        if not bonus_match:
            exceptions.append({
                'ISIN': isin, 'Script': script_code,
                'Issue': 'Bonus Mismatch',
                'Details': f"Input: {agg_bonus_recd}, Expected: {expected_bonus}"
            })

        # --- C. Dividend Verification ---
        total_dps = ca['total_dps']
        expected_dividend = agg_closing_units * total_dps
        dividend_diff = agg_dividend_recd - expected_dividend
        dividend_match = abs(dividend_diff) < 1.0 # Tolerance for currency rounding

        if not dividend_match:
             exceptions.append({
                'ISIN': isin, 'Script': script_code,
                'Issue': 'Dividend Mismatch',
                'Details': f"Input: {agg_dividend_recd}, Expected: {expected_dividend}"
            })

        # --- D. Market Price & Value Verification ---
        bhav_price = bhav_map.get(isin, 0.0)

        # Price Tolerance Rule: Absolute diff < 1
        price_diff = input_price - bhav_price
        price_match_initial = abs(price_diff) < 1.0

        # Expected Market Value using Aggregated Closing Units
        expected_mv = agg_closing_units * bhav_price

        # MV Tolerance Rule: Diff % <= 1%
        mv_diff = agg_market_value - expected_mv

        if expected_mv != 0:
            mv_diff_pct = (abs(mv_diff) / expected_mv) * 100
        else:
            mv_diff_pct = 0.0 if agg_market_value == 0 else 100.0

        mv_match = mv_diff_pct <= 1.0

        # If MV Match passes, we are good. If fails, it's an exception.
        # User said: "Price tolerance < 1 allowed. BUT MV tolerance > 1% -> Error."
        # This implies if MV matches, price is effectively verified/tolerated.

        if not mv_match:
             exceptions.append({
                'ISIN': isin, 'Script': script_code,
                'Issue': 'Market Value/Price Mismatch',
                'Details': f"MV Diff %: {mv_diff_pct:.2f}% (Limit 1%), Price Diff: {price_diff:.2f}"
            })

        # --- E. UGL Calculation ---
        # UGL = Market Value - Closing Amount
        # Use Verified/Expected MV for calculation per best practice (and user intent to fix logic)
        expected_ugl = expected_mv - agg_closing_amount

        # Collect Data
        record = {
            'ISIN': isin,
            'Script Code': script_code,
            'Name': name,

            # Closing
            'Agg Input Closing Units': agg_closing_units,
            'Portfolio Closing Units': portfolio_units,
            'Closing Diff': closing_diff,
            'Closing Match': closing_match,

            # Bonus
            'Agg Opening Units': agg_opening_units,
            'Agg Input Bonus': agg_bonus_recd,
            'Expected Bonus': expected_bonus,
            'Bonus Diff': bonus_diff,
            'Bonus Match': bonus_match,

            # Dividend
            'Agg Input Dividend': agg_dividend_recd,
            'Total DPS': total_dps,
            'Expected Dividend': expected_dividend,
            'Dividend Diff': dividend_diff,
            'Dividend Match': dividend_match,

            # Price & MV
            'Input Price (Avg)': input_price,
            'Bhav Price': bhav_price,
            'Price Diff': price_diff,
            'Agg Input MV': agg_market_value,
            'Expected MV': expected_mv,
            'MV Diff': mv_diff,
            'MV Diff %': mv_diff_pct,
            'MV Match': mv_match,

            # UGL
            'Agg Closing Amount': agg_closing_amount,
            'Calculated UGL': expected_ugl
        }

        detailed_data.append(record)

    # Create DataFrames
    df_results = pd.DataFrame(detailed_data)
    df_exceptions = pd.DataFrame(exceptions)

    # Summary
    if not df_results.empty:
        summary = {
            'Total ISINs': len(df_results),
            'Closing Units Mismatches': len(df_results[~df_results['Closing Match']]),
            'Bonus Mismatches': len(df_results[~df_results['Bonus Match']]),
            'Dividend Mismatches': len(df_results[~df_results['Dividend Match']]),
            'MV/Price Mismatches': len(df_results[~df_results['MV Match']])
        }
    else:
        summary = {'Total ISINs': 0}

    return summary, df_results, df_exceptions

def generate_excel_report(df_results, df_exceptions):
    """
    Generates the Excel file in memory using aggregated results.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:

        def write_sheet(cols, sheet_name):
            if df_results.empty:
                pd.DataFrame(columns=cols).to_excel(writer, sheet_name=sheet_name, index=False)
            else:
                # Ensure columns exist before writing
                valid_cols = [c for c in cols if c in df_results.columns]
                df_results[valid_cols].to_excel(writer, sheet_name=sheet_name, index=False)

        # 1. Closing Units
        write_sheet(['ISIN', 'Script Code', 'Name', 'Agg Input Closing Units', 'Portfolio Closing Units', 'Closing Diff', 'Closing Match'], 'Closing Units Verification')

        # 2. Bonus
        write_sheet(['ISIN', 'Script Code', 'Name', 'Agg Opening Units', 'Agg Input Bonus', 'Expected Bonus', 'Bonus Diff', 'Bonus Match'], 'Bonus Verification')

        # 3. Dividend
        write_sheet(['ISIN', 'Script Code', 'Name', 'Agg Input Closing Units', 'Total DPS', 'Agg Input Dividend', 'Expected Dividend', 'Dividend Diff', 'Dividend Match'], 'Dividend Working')

        # 4. Market Price & Value
        write_sheet(['ISIN', 'Script Code', 'Name', 'Input Price (Avg)', 'Bhav Price', 'Price Diff', 'Agg Input MV', 'Expected MV', 'MV Diff', 'MV Diff %', 'MV Match'], 'Market Price & MV Verification')

        # 5. UGL
        write_sheet(['ISIN', 'Script Code', 'Name', 'Agg Closing Amount', 'Expected MV', 'Calculated UGL'], 'UGL Calculation')

        # 6. Exceptions
        if not df_exceptions.empty:
            df_exceptions.to_excel(writer, sheet_name='Exception Report', index=False)
        else:
            pd.DataFrame(columns=['ISIN', 'Script', 'Issue', 'Details']).to_excel(writer, sheet_name='Exception Report', index=False)

    return output.getvalue()
