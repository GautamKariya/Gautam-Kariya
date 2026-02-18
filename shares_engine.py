import pandas as pd
import numpy as np
from io import BytesIO

def run_verification(shares_df, portfolio_df, corp_action_df, bhav_copy_df):
    """
    Runs the verification logic using Hybrid Approach:
    - ISIN Aggregation for Closing Units, Bonus, Dividend.
    - Row-wise for Market Price, Market Value, UGL.

    Returns:
        summary_stats (dict): Counts of mismatches.
        output_dfs (dict): DataFrames for Excel sheets.
        exceptions_df (DataFrame): Consolidated exceptions.
    """

    # 1. Pre-process Corporate Actions (Group by script_code)
    corp_actions = {}
    if corp_action_df is not None and not corp_action_df.empty:
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
        portfolio_map = portfolio_df.set_index('isin')['portfolio_closing_units'].to_dict()

    bhav_map = {}
    if bhav_copy_df is not None and not bhav_copy_df.empty:
        if 'ISIN' in bhav_copy_df.columns:
            bhav_map = bhav_copy_df.set_index('ISIN')['bhav_close'].to_dict()
        elif 'isin' in bhav_copy_df.columns:
            bhav_map = bhav_copy_df.set_index('isin')['bhav_close'].to_dict()

    # 3. Aggregation Step (ISIN Level)
    if shares_df is None or shares_df.empty:
        return {'Error': 'No Shares Input'}, {}, pd.DataFrame()

    # Ensure numeric columns
    num_cols = ['opening_units', 'bonus_recd', 'closing_units', 'closing_amount', 'dividend_recd', 'market_value', 'market_price']
    for c in num_cols:
        if c not in shares_df.columns:
            shares_df[c] = 0.0

    # Aggregation for Closing/Bonus/Dividend
    agg_cols = ['opening_units', 'bonus_recd', 'closing_units', 'dividend_recd']
    meta_cols = ['script_code', 'name']

    agg_dict = {c: 'sum' for c in agg_cols}
    for c in meta_cols:
        if c in shares_df.columns:
            agg_dict[c] = 'first'

    shares_agg = shares_df.groupby('isin', as_index=False).agg(agg_dict)

    # Initialize Output Containers
    exceptions = []

    # --- MODULE 1: CLOSING UNITS (AGGREGATED) ---
    res_closing = []
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        agg_closing = row['closing_units']
        port_closing = portfolio_map.get(isin, 0.0)

        diff = agg_closing - port_closing
        match = abs(diff) < 0.01

        res_closing.append({
            'ISIN': isin, 'Script Code': row.get('script_code', ''), 'Name': row.get('name', ''),
            'Agg Input Closing Units': agg_closing, 'Portfolio Closing Units': port_closing,
            'Diff': diff, 'Match': match
        })

        if not match:
            exceptions.append({'ISIN': isin, 'Script': row.get('script_code', ''), 'Issue': 'Closing Units Mismatch', 'Details': f"Agg: {agg_closing}, Port: {port_closing}"})

    df_closing = pd.DataFrame(res_closing)

    # --- MODULE 2: BONUS (AGGREGATED) ---
    res_bonus = []
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        script = row.get('script_code', '')
        agg_opening = row['opening_units']
        agg_bonus = row['bonus_recd']

        ca = corp_actions.get(script, {'bonus_ratios': [], 'total_dps': 0.0})
        expected_bonus = 0.0
        for ratio in ca['bonus_ratios']:
            expected_bonus += agg_opening * ratio

        diff = agg_bonus - expected_bonus
        match = abs(diff) < 0.01

        res_bonus.append({
            'ISIN': isin, 'Script Code': script, 'Name': row.get('name', ''),
            'Agg Opening Units': agg_opening, 'Agg Input Bonus': agg_bonus,
            'Expected Bonus': expected_bonus, 'Diff': diff, 'Match': match
        })

        if not match:
             exceptions.append({'ISIN': isin, 'Script': script, 'Issue': 'Bonus Mismatch', 'Details': f"Input: {agg_bonus}, Expected: {expected_bonus}"})

    df_bonus = pd.DataFrame(res_bonus)

    # --- MODULE 3: DIVIDEND (AGGREGATED) ---
    res_dividend = []
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        script = row.get('script_code', '')
        agg_closing = row['closing_units']
        agg_dividend = row['dividend_recd']

        ca = corp_actions.get(script, {'bonus_ratios': [], 'total_dps': 0.0})
        total_dps = ca['total_dps']
        expected_dividend = agg_closing * total_dps

        diff = agg_dividend - expected_dividend
        match = abs(diff) < 1.0

        res_dividend.append({
            'ISIN': isin, 'Script Code': script, 'Name': row.get('name', ''),
            'Agg Closing Units': agg_closing, 'Total DPS': total_dps,
            'Agg Input Dividend': agg_dividend, 'Expected Dividend': expected_dividend,
            'Diff': diff, 'Match': match
        })

        if not match:
            exceptions.append({'ISIN': isin, 'Script': script, 'Issue': 'Dividend Mismatch', 'Details': f"Input: {agg_dividend}, Expected: {expected_dividend}"})

    df_dividend = pd.DataFrame(res_dividend)

    # --- MODULE 4, 5, 6: PRICE, MV, UGL (ROW-WISE) ---
    # Iterate original shares_df
    res_price_mv = []
    res_ugl = []

    for idx, row in shares_df.iterrows():
        isin = row.get('isin', '')
        script = row.get('script_code', '')
        name = row.get('name', '')

        closing_units = row.get('closing_units', 0.0)
        closing_amount = row.get('closing_amount', 0.0)
        input_price = row.get('market_price', 0.0)
        input_mv = row.get('market_value', 0.0)

        bhav_price = bhav_map.get(isin, 0.0)

        # Price Verification
        price_diff = input_price - bhav_price
        price_match = abs(price_diff) < 1.0

        # MV Verification
        expected_mv = closing_units * bhav_price
        mv_diff = input_mv - expected_mv
        if expected_mv != 0:
            mv_diff_pct = (abs(mv_diff) / expected_mv) * 100
        else:
            mv_diff_pct = 0.0 if input_mv == 0 else 100.0

        mv_match = mv_diff_pct <= 1.0

        # Combined Exception Logic
        # "Even if price diff < 1, calculate Expected MV. If MV Diff % > 1% -> Error."
        # This implies checking MV match is the primary failure condition?
        # Or do we report Price mismatch separately?
        # Usually separate columns.

        if not mv_match:
             exceptions.append({'ISIN': isin, 'Script': script, 'Issue': 'MV/Price Mismatch', 'Details': f"Row {idx+2}: MV Diff % {mv_diff_pct:.2f}%, Price Diff {price_diff:.2f}"})

        res_price_mv.append({
            'ISIN': isin, 'Script Code': script, 'Name': name,
            'Input Price': input_price, 'Bhav Price': bhav_price, 'Price Diff': price_diff,
            'Input MV': input_mv, 'Expected MV': expected_mv,
            'MV Diff': mv_diff, 'MV Diff %': mv_diff_pct, 'MV Match': mv_match
        })

        # UGL Calculation
        # UGL = Expected MV - Closing Amount (Row-wise)
        calculated_ugl = expected_mv - closing_amount

        res_ugl.append({
            'ISIN': isin, 'Script Code': script, 'Name': name,
            'Closing Amount': closing_amount, 'Expected MV': expected_mv,
            'Calculated UGL': calculated_ugl
        })

    df_price_mv = pd.DataFrame(res_price_mv)
    df_ugl = pd.DataFrame(res_ugl)

    # Exceptions DF
    df_exceptions = pd.DataFrame(exceptions)

    # Summary
    summary = {
        'Total ISINs (Agg)': len(shares_agg),
        'Total Input Rows': len(shares_df),
        'Closing Units Mismatches': len(df_closing[~df_closing['Match']]),
        'Bonus Mismatches': len(df_bonus[~df_bonus['Match']]),
        'Dividend Mismatches': len(df_dividend[~df_dividend['Match']]),
        'MV/Price Mismatches': len(df_price_mv[~df_price_mv['MV Match']])
    }

    output_dfs = {
        'Closing Units': df_closing,
        'Bonus': df_bonus,
        'Dividend': df_dividend,
        'Price_MV': df_price_mv,
        'UGL': df_ugl
    }

    return summary, output_dfs, df_exceptions

def generate_excel_report(output_dfs, df_exceptions):
    """
    Generates Excel report from dictionary of DataFrames.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:

        # Helper to write
        def write(df, name):
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)
            else:
                pd.DataFrame().to_excel(writer, sheet_name=name, index=False)

        write(output_dfs.get('Closing Units'), 'Closing Units Verification')
        write(output_dfs.get('Bonus'), 'Bonus Verification')
        write(output_dfs.get('Dividend'), 'Dividend Working')
        write(output_dfs.get('Price_MV'), 'Market Price & MV Verification')
        write(output_dfs.get('UGL'), 'UGL Calculation')
        write(df_exceptions, 'Exception Report')

    return output.getvalue()
