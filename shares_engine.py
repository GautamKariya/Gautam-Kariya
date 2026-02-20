import pandas as pd
import numpy as np
from io import BytesIO

def run_verification(shares_df, portfolio_df, corp_action_df, bhav_copy_df, manual_df=None):
    """
    Runs the verification logic using Hybrid Approach with STRICT Validation and UPPERCASE Normalization.
    Enhancements: Investment Name inclusion, % Difference calculations, formatted summary.
    """

    # --- 0. NORMALIZATION & PRE-EXECUTION CHECKS ---

    # Normalize Input Columns to Uppercase
    if shares_df is not None:
        shares_df.columns = [str(c).strip().upper() for c in shares_df.columns]
    if portfolio_df is not None:
        portfolio_df.columns = [str(c).strip().upper() for c in portfolio_df.columns]
    if corp_action_df is not None:
        corp_action_df.columns = [str(c).strip().upper() for c in corp_action_df.columns]
    if bhav_copy_df is not None:
        bhav_copy_df.columns = [str(c).strip().upper() for c in bhav_copy_df.columns]
    if manual_df is not None:
        manual_df.columns = [str(c).strip().upper() for c in manual_df.columns]

    # Required Columns (Using Uppercase)
    required_shares_cols = [
        'ISIN', 'SCRIPT_CODE', 'OPENING_UNITS', 'CLOSING_UNITS',
        'CLOSING_AMOUNT', 'DIVIDEND_RECD', 'UGL', 'MARKET_VALUE',
        'PURCHASE_UNITS', 'SALES_UNITS', 'BONUS_RECD'
    ]
    missing_shares = [c for c in required_shares_cols if c not in shares_df.columns]
    if missing_shares:
        raise ValueError(f"STOP: Missing mandatory columns in Shares Input: {', '.join(missing_shares)}")

    required_bhav_cols = ['ISIN', 'BHAV_CLOSE']
    missing_bhav = [c for c in required_bhav_cols if c not in bhav_copy_df.columns]
    if missing_bhav:
        raise ValueError(f"STOP: Missing mandatory columns in Bhav Copy: {', '.join(missing_bhav)}")

    if corp_action_df is not None and not corp_action_df.empty:
        required_ca_cols = ['SCRIPT_CODE', 'ACTION_TYPE', 'VALUE']
        missing_ca = [c for c in required_ca_cols if c not in corp_action_df.columns]
        if missing_ca:
            raise ValueError(f"STOP: Missing mandatory columns in Corp Action: {', '.join(missing_ca)}")

    # --- 1. AGGREGATION (STRICT) ---

    agg_dict = {
        'OPENING_UNITS': 'sum',
        'PURCHASE_UNITS': 'sum',
        'BONUS_RECD': 'sum',
        'SALES_UNITS': 'sum',
        'CLOSING_UNITS': 'sum',

        'OPENING_AMOUNT': 'sum',
        'PURCHASE_AMOUNT': 'sum',
        'SALES_AMOUNT': 'sum',
        'CLOSING_AMOUNT': 'sum',

        'DIVIDEND_RECD': 'sum',
        'UGL': 'sum',
        'MARKET_VALUE': 'sum'
    }

    # Metadata
    meta_cols = ['SCRIPT_CODE', 'NAME']
    for c in meta_cols:
        if c in shares_df.columns:
            agg_dict[c] = 'first'

    # Check Agg keys
    for k in agg_dict:
        if k not in shares_df.columns and k not in meta_cols:
             raise ValueError(f"STOP: Aggregation field '{k}' missing in input.")

    shares_agg = shares_df.groupby('ISIN', as_index=False).agg(agg_dict)

    if len(shares_agg) != shares_df['ISIN'].nunique():
        raise ValueError("STOP: Aggregation failure detected. Unique ISIN count mismatch.")

    # --- 2. PRE-PROCESS REFERENCE DATA ---

    # Corp Actions
    corp_actions = {}
    if corp_action_df is not None and not corp_action_df.empty:
        for script_code, group in corp_action_df.groupby('SCRIPT_CODE'):
            bonuses = group[group['ACTION_TYPE'] == 'Bonus']
            dividends = group[group['ACTION_TYPE'] == 'Dividend']

            corp_actions[script_code] = {
                'bonus_ratios': bonuses['VALUE'].tolist(),
                'total_dps': dividends['VALUE'].sum()
            }

    # Portfolio Map
    portfolio_map = {}
    if portfolio_df is not None and not portfolio_df.empty:
        portfolio_map = portfolio_df.set_index('ISIN')['PORTFOLIO_CLOSING_UNITS'].to_dict()

    # Bhav Map (Strict)
    bhav_map = {}
    if not bhav_copy_df.empty:
        bhav_map = bhav_copy_df.set_index('ISIN')['BHAV_CLOSE'].to_dict()

    # Manual Map
    manual_map = {}
    if manual_df is not None and not manual_df.empty:
        for _, row in manual_df.iterrows():
            isin_key = str(row.get('ISIN', '')).strip().upper()
            if isin_key:
                manual_map[isin_key] = {
                    'div_rate': float(row.get('DIVIDEND RATE', 0.0) or 0.0),
                    'repay_rate': float(row.get('REPAYMENT RATE', 0.0) or 0.0)
                }

    # --- 3. VERIFICATION MODULES (AGGREGATED) ---

    exceptions = []

    # Pre-calculate Expected Bonus
    isin_bonus_map = {}
    for _, row in shares_agg.iterrows():
        isin = row['ISIN']
        script = str(row.get('SCRIPT_CODE', '')).strip()
        agg_opening = row['OPENING_UNITS']

        ca = corp_actions.get(script, {'bonus_ratios': [], 'total_dps': 0.0})
        expected_bonus = 0.0
        for ratio in ca['bonus_ratios']:
            expected_bonus += agg_opening * ratio
        isin_bonus_map[isin] = expected_bonus

    # MODULE A: CLOSING UNITS
    res_closing = []
    for _, row in shares_agg.iterrows():
        isin = row['ISIN']
        agg_closing = row['CLOSING_UNITS']
        port_closing = portfolio_map.get(isin, 0.0)

        agg_opening = row['OPENING_UNITS']
        agg_purchase = row['PURCHASE_UNITS']
        agg_sales = row['SALES_UNITS']

        expected_bonus = isin_bonus_map.get(isin, 0.0)

        # Logic Change: Identify REIT by presence in Manual Map
        is_reit = isin in manual_map
        manual = manual_map.get(isin)
        repay_rate = manual['repay_rate'] if manual else 0.0

        if is_reit:
            # REIT Logic
            # If Repayment Rate > 0, assume Sales Units are Repayment Units (don't reduce holding)
            # If Repayment Rate == 0, assume Sales Units are Real Sales (reduce holding)
            if repay_rate > 0:
                calc_closing = agg_opening + agg_purchase + expected_bonus
                used_sales = 0
            else:
                calc_closing = agg_opening + agg_purchase + expected_bonus - agg_sales
                used_sales = agg_sales
        else:
            # Normal Equity: Always subtract Sales
            calc_closing = agg_opening + agg_purchase + expected_bonus - agg_sales
            used_sales = agg_sales

        form_diff = agg_closing - calc_closing
        form_match = abs(form_diff) < 0.01

        port_diff = agg_closing - port_closing
        port_match = abs(port_diff) < 0.01

        res_closing.append({
            'ISIN': isin, 'SCRIPT_CODE': row.get('SCRIPT_CODE', ''), 'NAME': row.get('NAME', ''),
            'CALC_CLOSING': calc_closing, 'INPUT_AGG_CLOSING': agg_closing,
            'FORMULA_MATCH': form_match,
            'PORTFOLIO_CLOSING': port_closing, 'PORT_MATCH': port_match
        })

        if not form_match:
            exceptions.append({'ISIN': isin, 'Module': 'Closing Units', 'Match': False, 'Details': f"Formula Fail. Calc: {calc_closing}, Input: {agg_closing}"})
        if not port_match:
            exceptions.append({'ISIN': isin, 'Module': 'Closing Units', 'Match': False, 'Details': f"Portfolio Fail. Port: {port_closing}, Input: {agg_closing}"})

    # MODULE B: CLOSING AMOUNT
    res_amount = []
    for _, row in shares_agg.iterrows():
        isin = row['ISIN']
        agg_closing_amt = row['CLOSING_AMOUNT']

        manual = manual_map.get(isin)
        repay_rate = manual['repay_rate'] if manual else 0.0

        repay_validation = "N/A"
        if repay_rate > 0:
            exp_repay = row['SALES_UNITS'] * repay_rate
            if abs(row['SALES_AMOUNT'] - exp_repay) > 1.0:
                repay_validation = "Mismatch"
                exceptions.append({'ISIN': isin, 'Module': 'REIT Validation', 'Match': False, 'Details': f"Sales Amt {row['SALES_AMOUNT']} != Expected {exp_repay}"})
            else:
                repay_validation = "Validated"

        calc_amt = row['OPENING_AMOUNT'] + row['PURCHASE_AMOUNT'] - row['SALES_AMOUNT']

        diff = agg_closing_amt - calc_amt
        match = abs(diff) < 1.0

        res_amount.append({
            'ISIN': isin, 'NAME': row.get('NAME', ''),
            'CALC_CLOSING_AMT': calc_amt, 'INPUT_CLOSING_AMT': agg_closing_amt, 'MATCH': match, 'REPAY_VALID': repay_validation
        })

        if not match:
            exceptions.append({'ISIN': isin, 'Module': 'Closing Amount', 'Match': False, 'Details': f"Calc: {calc_amt}, Input: {agg_closing_amt}"})

    # MODULE C: BONUS
    res_bonus = []
    for _, row in shares_agg.iterrows():
        isin = row['ISIN']
        exp_bonus = isin_bonus_map.get(isin, 0.0)
        inp_bonus = row['BONUS_RECD']

        diff = inp_bonus - exp_bonus
        match = abs(diff) < 0.01

        res_bonus.append({
            'ISIN': isin, 'NAME': row.get('NAME', ''),
            'EXPECTED_BONUS': exp_bonus, 'INPUT_BONUS': inp_bonus, 'MATCH': match
        })

        if not match:
            exceptions.append({'ISIN': isin, 'Module': 'Bonus', 'Match': False, 'Details': f"Exp: {exp_bonus}, Inp: {inp_bonus}"})

    # MODULE D: DIVIDEND
    res_dividend = []
    for _, row in shares_agg.iterrows():
        isin = row['ISIN']
        script = str(row.get('SCRIPT_CODE', '')).strip()
        agg_closing = row['CLOSING_UNITS']
        inp_div = row['DIVIDEND_RECD']

        manual = manual_map.get(isin)
        if manual and manual['div_rate'] > 0:
            total_dps = manual['div_rate']
        else:
            ca = corp_actions.get(script, {'bonus_ratios': [], 'total_dps': 0.0})
            total_dps = ca['total_dps']

        exp_div = agg_closing * total_dps
        diff = inp_div - exp_div
        match = abs(diff) <= 2.0

        # Calculate % Diff
        div_diff_pct = (diff / exp_div) if exp_div != 0 else 0.0

        res_dividend.append({
            'ISIN': isin, 'NAME': row.get('NAME', ''),
            'EXPECTED_DIVIDEND': exp_div, 'INPUT_DIVIDEND': inp_div, 'DIFF': diff, 'DIFF_%': div_diff_pct, 'MATCH': match
        })

        if not match:
            exceptions.append({'ISIN': isin, 'Module': 'Dividend', 'Match': False, 'Details': f"Exp: {exp_div}, Inp: {inp_div}"})

    # MODULE E: MARKET PRICE & VALUE (Row-wise)
    res_mv_ugl = []
    isin_expected_mv_map = {}

    # Store aggregated row diffs for logging? No, summary sheet uses Aggregated data.
    # Exception detail uses row-wise.

    for idx, row in shares_df.iterrows():
        isin = str(row.get('ISIN', '')).strip()

        closing_units = row.get('CLOSING_UNITS', 0.0)
        input_price = row.get('MARKET_PRICE', 0.0)
        input_mv = row.get('MARKET_VALUE', 0.0)

        if isin not in bhav_map:
            raise ValueError(f"STOP: ISIN {isin} not found in Bhav Copy.")

        bhav_price = bhav_map[isin]

        expected_mv = closing_units * bhav_price
        isin_expected_mv_map[isin] = isin_expected_mv_map.get(isin, 0.0) + expected_mv

        # Row-wise checks (for exception details only)
        mv_diff = input_mv - expected_mv
        mv_match = False
        if expected_mv != 0:
            if (abs(mv_diff) / expected_mv) <= 0.01: mv_match = True
        else:
            if input_mv == 0: mv_match = True

        if not mv_match:
             exceptions.append({'ISIN': isin, 'Module': 'Market Value', 'Match': False, 'Details': f"Row MV Mismatch"})

    # MODULE F: UGL (AGGREGATED)
    for _, row in shares_agg.iterrows():
        isin = row['ISIN']
        agg_closing_amt = row['CLOSING_AMOUNT']
        agg_input_ugl = row['UGL']
        agg_input_mv = row['MARKET_VALUE']

        agg_expected_mv = isin_expected_mv_map.get(isin, 0.0)

        # MV Aggregated Calculations
        mv_diff = agg_expected_mv - agg_input_mv
        mv_diff_pct = (mv_diff / agg_expected_mv) if agg_expected_mv != 0 else 0.0

        mv_match = False
        if agg_expected_mv != 0:
            if abs(mv_diff_pct) <= 0.01: mv_match = True
        else:
            if agg_input_mv == 0: mv_match = True

        # UGL Calculation
        calc_ugl = agg_expected_mv - agg_closing_amt
        ugl_diff = calc_ugl - agg_input_ugl
        ugl_match = abs(ugl_diff) <= 2.0

        ugl_diff_pct = (ugl_diff / calc_ugl) if calc_ugl != 0 else 0.0

        res_mv_ugl.append({
            'ISIN': isin, 'NAME': row.get('NAME', ''),
            'EXPECTED_MV': agg_expected_mv, 'INPUT_MV': agg_input_mv, 'MV_DIFF': mv_diff, 'MV_DIFF_%': mv_diff_pct, 'MV_MATCH': mv_match,
            'CLOSING_AMOUNT': agg_closing_amt, 'CALCULATED_UGL': calc_ugl, 'INPUT_UGL': agg_input_ugl,
            'UGL_DIFF': ugl_diff, 'UGL_DIFF_%': ugl_diff_pct, 'UGL_MATCH': ugl_match
        })

        if not ugl_match:
            exceptions.append({'ISIN': isin, 'Module': 'UGL', 'Match': False, 'Details': f"Calc: {calc_ugl}, Inp: {agg_input_ugl}"})

    # --- 4. OUTPUT GENERATION ---
    df_closing = pd.DataFrame(res_closing)
    df_amount = pd.DataFrame(res_amount)
    df_bonus = pd.DataFrame(res_bonus)
    df_dividend = pd.DataFrame(res_dividend)
    df_mv_ugl = pd.DataFrame(res_mv_ugl)

    # SHARES AUDIT SUMMARY
    summary_base = shares_agg[['ISIN', 'SCRIPT_CODE', 'NAME']].rename(columns={'NAME': 'INVESTMENT NAME', 'SCRIPT_CODE': 'SCRIPT CODE'})

    # Merge Results
    summary_final = summary_base.merge(df_closing[['ISIN', 'PORT_MATCH']].rename(columns={'PORT_MATCH': 'CLOSING MATCH'}), on='ISIN', how='left')
    summary_final = summary_final.merge(df_bonus[['ISIN', 'MATCH']].rename(columns={'MATCH': 'BONUS MATCH'}), on='ISIN', how='left')
    summary_final = summary_final.merge(df_dividend[['ISIN', 'MATCH', 'DIFF', 'DIFF_%']].rename(columns={'MATCH': 'DIVIDEND MATCH', 'DIFF': 'DIVIDEND DIFF', 'DIFF_%': 'DIVIDEND DIFF %'}), on='ISIN', how='left')
    summary_final = summary_final.merge(df_mv_ugl[['ISIN', 'MV_MATCH', 'UGL_MATCH', 'MV_DIFF', 'MV_DIFF_%', 'UGL_DIFF', 'UGL_DIFF_%']].rename(columns={
        'MV_MATCH': 'MV MATCH', 'UGL_MATCH': 'UGL MATCH',
        'MV_DIFF': 'MV DIFF', 'MV_DIFF_%': 'MV DIFF %',
        'UGL_DIFF': 'UGL DIFF', 'UGL_DIFF_%': 'UGL DIFF %'
    }), on='ISIN', how='left')

    # Reorder Columns
    final_cols = [
        'INVESTMENT NAME', 'ISIN', 'SCRIPT CODE',
        'CLOSING MATCH', 'BONUS MATCH', 'DIVIDEND MATCH', 'MV MATCH', 'UGL MATCH',
        'MV DIFF', 'MV DIFF %', 'UGL DIFF', 'UGL DIFF %', 'DIVIDEND DIFF', 'DIVIDEND DIFF %'
    ]
    summary_final = summary_final[final_cols]

    output_dfs = {
        'SHARES AUDIT SUMMARY': summary_final,
        'Closing Units': df_closing,
        'Closing Amount': df_amount,
        'Bonus': df_bonus,
        'Dividend': df_dividend,
        'MV_UGL': df_mv_ugl
    }

    # Stats for UI
    failed_rows = summary_final[
        (~summary_final['CLOSING MATCH']) |
        (~summary_final['BONUS MATCH']) |
        (~summary_final['DIVIDEND MATCH']) |
        (~summary_final['MV MATCH']) |
        (~summary_final['UGL MATCH'])
    ]

    stats = {
        'Total ISINs': len(shares_agg),
        'Failed ISINs': len(failed_rows)
    }

    return stats, output_dfs, pd.DataFrame(exceptions)

def generate_excel_report(output_dfs, df_exceptions):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        pct_fmt = workbook.add_format({'num_format': '0.00%'})
        num_fmt = workbook.add_format({'num_format': '#,##0.00'})

        def write(df, name):
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)
                worksheet = writer.sheets[name]
                for i, col in enumerate(df.columns):
                    if '%' in col:
                        worksheet.set_column(i, i, None, pct_fmt)
                    elif any(k in col for k in ['DIFF', 'AMOUNT', 'VALUE', 'PRICE', 'DIVIDEND', 'UGL', 'EXP', 'INP', 'CALC']):
                        if 'MATCH' not in col and 'ISIN' not in col and 'CODE' not in col and 'NAME' not in col:
                            worksheet.set_column(i, i, None, num_fmt)
            else:
                pd.DataFrame().to_excel(writer, sheet_name=name, index=False)

        write(output_dfs.get('SHARES AUDIT SUMMARY'), 'SHARES AUDIT SUMMARY')
        write(output_dfs.get('Closing Units'), 'Closing Units Verification')
        write(output_dfs.get('Closing Amount'), 'Closing Amount Verification')
        write(output_dfs.get('Bonus'), 'Bonus Verification')
        write(output_dfs.get('Dividend'), 'Dividend Working')
        write(output_dfs.get('MV_UGL'), 'MV & UGL Verification')
        write(df_exceptions, 'Detailed Exceptions')

    return output.getvalue()
