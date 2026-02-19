import pandas as pd
import numpy as np
from io import BytesIO

def run_verification(shares_df, portfolio_df, corp_action_df, bhav_copy_df, manual_df=None):
    """
    Runs the verification logic using Hybrid Approach.
    """

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

    # 2. Pre-process Manual Data (REIT)
    manual_map = {}
    if manual_df is not None and not manual_df.empty:
        # Map ISIN -> {Dividend Rate, Repayment Rate}
        for _, row in manual_df.iterrows():
            isin_key = str(row.get('ISIN', '')).strip().upper()
            if isin_key:
                manual_map[isin_key] = {
                    'div_rate': float(row.get('Dividend Rate', 0.0) or 0.0),
                    'repay_rate': float(row.get('Repayment Rate', 0.0) or 0.0)
                }

    # 3. Pre-process Portfolio and Bhav Copy
    portfolio_map = {}
    if portfolio_df is not None and not portfolio_df.empty:
        portfolio_map = portfolio_df.set_index('isin')['portfolio_closing_units'].to_dict()

    bhav_map = {}
    if bhav_copy_df is not None and not bhav_copy_df.empty:
        if 'ISIN' in bhav_copy_df.columns:
            bhav_map = bhav_copy_df.set_index('ISIN')['bhav_close'].to_dict()
        elif 'isin' in bhav_copy_df.columns:
            bhav_map = bhav_copy_df.set_index('isin')['bhav_close'].to_dict()

    # 4. Aggregation Step (ISIN Level)
    if shares_df is None or shares_df.empty:
        return {'Error': 'No Shares Input'}, {}, pd.DataFrame()

    # Ensure numeric columns
    num_cols = [
        'opening_units', 'opening_amount',
        'purchase_units', 'purchase_amount',
        'sales_units', 'sales_amount',
        'bonus_recd',
        'closing_units', 'closing_amount',
        'dividend_recd', 'market_value', 'market_price', 'ugl'
    ]
    for c in num_cols:
        if c not in shares_df.columns:
            shares_df[c] = 0.0

    # Aggregation
    agg_cols = [
        'opening_units', 'opening_amount',
        'purchase_units', 'purchase_amount',
        'sales_units', 'sales_amount',
        'bonus_recd',
        'closing_units', 'closing_amount',
        'dividend_recd', 'ugl'
    ]
    meta_cols = ['script_code', 'name']

    agg_dict = {c: 'sum' for c in agg_cols}
    for c in meta_cols:
        if c in shares_df.columns:
            agg_dict[c] = 'first'

    shares_agg = shares_df.groupby('isin', as_index=False).agg(agg_dict)

    exceptions = []

    # Pre-calculate Expected Bonus for Verification (but reverted logic uses Input Bonus for Closing Calc)
    isin_bonus_map = {}
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        script = str(row.get('script_code', '')).strip()
        agg_opening = row['opening_units']

        ca = corp_actions.get(script, {'bonus_ratios': [], 'total_dps': 0.0})
        expected_bonus = 0.0
        for ratio in ca['bonus_ratios']:
            expected_bonus += agg_opening * ratio

        isin_bonus_map[isin] = expected_bonus

    # --- MODULE 1: CLOSING UNITS (AGGREGATED + FORMULA CHECK) ---
    res_closing = []
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        agg_closing = row['closing_units']
        port_closing = portfolio_map.get(isin, 0.0)

        agg_opening = row['opening_units']
        agg_purchase = row['purchase_units']
        agg_sales = row['sales_units']
        agg_bonus = row['bonus_recd'] # Input Bonus

        manual = manual_map.get(isin)
        is_reit_repayment = False
        if manual and manual['repay_rate'] > 0:
            is_reit_repayment = True

        if is_reit_repayment:
            # REIT Rule: Closing = Opening + Purchase + Bonus (Ignore Sales)
            # Reverted: Use agg_bonus (Input Bonus)
            calc_closing = agg_opening + agg_purchase + agg_bonus
            used_sales = 0
        else:
            # Standard Rule: Closing = Opening + Purchase + Bonus - Sales
            calc_closing = agg_opening + agg_purchase + agg_bonus - agg_sales
            used_sales = agg_sales

        formula_diff = agg_closing - calc_closing
        formula_match = abs(formula_diff) < 0.01

        port_diff = agg_closing - port_closing
        port_match = abs(port_diff) < 0.01

        res_closing.append({
            'ISIN': isin, 'Script Code': row.get('script_code', ''),
            'Opening Units': agg_opening, 'Purchase Units': agg_purchase,
            'Bonus Units': agg_bonus, 'Sales Units': agg_sales, 'Used Sales': used_sales,
            'Calc Closing': calc_closing, 'Input Agg Closing': agg_closing,
            'Formula Diff': formula_diff, 'Formula Match': formula_match,
            'Portfolio Closing': port_closing, 'Port Diff': port_diff, 'Port Match': port_match,
            'Is REIT': is_reit_repayment
        })

        if not formula_match:
            exceptions.append({'ISIN': isin, 'Script': row.get('script_code', ''), 'Issue': 'Closing Units Formula Mismatch', 'Details': f"Calc: {calc_closing}, Input: {agg_closing}"})
        if not port_match:
            exceptions.append({'ISIN': isin, 'Script': row.get('script_code', ''), 'Issue': 'Portfolio Closing Mismatch', 'Details': f"Input: {agg_closing}, Port: {port_closing}"})

    df_closing = pd.DataFrame(res_closing)

    # --- MODULE 2: CLOSING AMOUNT (AGGREGATED) ---
    res_amount = []
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        agg_closing_amt = row['closing_amount']

        agg_opening_amt = row['opening_amount']
        agg_purchase_amt = row['purchase_amount']
        agg_sales_amt = row['sales_amount']
        agg_sales_units = row['sales_units']

        manual = manual_map.get(isin, {'div_rate': 0.0, 'repay_rate': 0.0})
        repay_rate = manual['repay_rate']

        validation_status = "N/A"
        if repay_rate > 0:
            expected_repayment = agg_sales_units * repay_rate
            if abs(agg_sales_amt - expected_repayment) < 1.0:
                validation_status = "Validated"
            else:
                validation_status = "Mismatch"
                exceptions.append({'ISIN': isin, 'Script': row.get('script_code', ''), 'Issue': 'REIT Repayment Mismatch', 'Details': f"Sales Amt: {agg_sales_amt}, Expected: {expected_repayment}"})

        calc_closing_amt = agg_opening_amt + agg_purchase_amt - agg_sales_amt

        diff = agg_closing_amt - calc_closing_amt
        match = abs(diff) < 1.0

        res_amount.append({
            'ISIN': isin, 'Script Code': row.get('script_code', ''),
            'Opening Amt': agg_opening_amt, 'Purchase Amt': agg_purchase_amt,
            'Sales Amt': agg_sales_amt,
            'Repayment Rate': repay_rate,
            'Repayment Validation': validation_status,
            'Calc Closing Amt': calc_closing_amt, 'Input Agg Closing Amt': agg_closing_amt,
            'Diff': diff, 'Match': match
        })

        if not match:
             exceptions.append({'ISIN': isin, 'Script': row.get('script_code', ''), 'Issue': 'Closing Amount Mismatch', 'Details': f"Calc: {calc_closing_amt}, Input: {agg_closing_amt}"})

    df_amount = pd.DataFrame(res_amount)

    # --- MODULE 3: BONUS VERIFICATION (AGGREGATED) ---
    res_bonus = []
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        script = str(row.get('script_code', '')).strip()
        agg_opening = row['opening_units']
        agg_bonus = row['bonus_recd']

        expected_bonus = isin_bonus_map.get(isin, 0.0)

        diff = agg_bonus - expected_bonus
        match = abs(diff) < 0.01

        res_bonus.append({
            'ISIN': isin, 'Script Code': script,
            'Agg Opening Units': agg_opening, 'Agg Input Bonus': agg_bonus,
            'Expected Bonus': expected_bonus, 'Diff': diff, 'Match': match
        })

        if not match:
             exceptions.append({'ISIN': isin, 'Script': script, 'Issue': 'Bonus Mismatch', 'Details': f"Input: {agg_bonus}, Expected: {expected_bonus}"})

    df_bonus = pd.DataFrame(res_bonus)

    # --- MODULE 4: DIVIDEND (AGGREGATED) ---
    res_dividend = []
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        script = str(row.get('script_code', '')).strip()
        agg_closing = row['closing_units']
        agg_dividend = row['dividend_recd']

        manual = manual_map.get(isin)
        if manual and manual['div_rate'] > 0:
            total_dps = manual['div_rate']
            source = "Manual"
        else:
            ca = corp_actions.get(script, {'bonus_ratios': [], 'total_dps': 0.0})
            total_dps = ca['total_dps']
            source = "Corp Action"

        expected_dividend = agg_closing * total_dps

        diff = agg_dividend - expected_dividend

        if abs(diff) <= 2:
            match = True
            diff = 0.0
        else:
            match = False

        res_dividend.append({
            'ISIN': isin, 'Script Code': script,
            'Agg Closing Units': agg_closing, 'Source': source, 'Total DPS': total_dps,
            'Agg Input Dividend': agg_dividend, 'Expected Dividend': expected_dividend,
            'Diff': diff, 'Match': match
        })

        if not match:
            exceptions.append({'ISIN': isin, 'Script': script, 'Issue': 'Dividend Mismatch', 'Details': f"Input: {agg_dividend}, Expected: {expected_dividend}"})

    df_dividend = pd.DataFrame(res_dividend)

    # --- MODULE 5: PRICE, MV (ROW-WISE) ---
    res_price_mv = []
    isin_expected_mv_map = {}

    for idx, row in shares_df.iterrows():
        isin = str(row.get('isin', '')).strip()
        script = str(row.get('script_code', '')).strip()
        name = row.get('name', '')

        closing_units = row.get('closing_units', 0.0)
        input_price = row.get('market_price', 0.0)
        input_mv = row.get('market_value', 0.0)

        price_found = False
        bhav_price = 0.0

        if isin in bhav_map:
            bhav_price = bhav_map[isin]
            price_found = True
        else:
            # Check raw df logic removed for brevity, assume exception
            exceptions.append({'ISIN': isin, 'Script': script, 'Issue': 'Bhav Price Missing', 'Details': "ISIN not found in Bhav Copy"})

        if not price_found:
             price_diff = input_price - 0
             price_match = False
        else:
            price_diff = input_price - bhav_price
            price_match = abs(price_diff) < 1.0

        expected_mv = closing_units * bhav_price
        mv_diff = input_mv - expected_mv

        # Accumulate Expected MV for ISIN
        isin_expected_mv_map[isin] = isin_expected_mv_map.get(isin, 0.0) + expected_mv

        if expected_mv != 0:
            mv_diff_pct = abs(mv_diff) / expected_mv
        else:
            if input_mv == 0:
                mv_diff_pct = 0.0
            else:
                mv_diff_pct = 1.0

        mv_match = mv_diff_pct <= 0.01

        if not mv_match:
             if price_found:
                 exceptions.append({'ISIN': isin, 'Script': script, 'Issue': 'MV/Price Mismatch', 'Details': f"MV Diff %: {mv_diff_pct*100:.2f}% (Limit 1%), Price Diff: {price_diff:.2f}"})

        res_price_mv.append({
            'ISIN': isin, 'Script Code': script, 'Name': name,
            'Input Price': input_price, 'Bhav Price': bhav_price, 'Price Diff': price_diff,
            'Input MV': input_mv, 'Expected MV': expected_mv,
            'MV Diff': mv_diff, 'MV Diff %': mv_diff_pct, 'MV Match': mv_match
        })

    df_price_mv = pd.DataFrame(res_price_mv)
    df_exceptions = pd.DataFrame(exceptions).drop_duplicates()

    # --- MODULE 6: UGL VERIFICATION (AGGREGATED) ---
    res_ugl = []
    for _, row in shares_agg.iterrows():
        isin = row['isin']
        agg_closing_amt = row['closing_amount']
        agg_input_ugl = row['ugl']

        agg_expected_mv = isin_expected_mv_map.get(isin, 0.0)

        calc_ugl = agg_expected_mv - agg_closing_amt

        ugl_diff = calc_ugl - agg_input_ugl

        if abs(ugl_diff) <= 2:
            match = True
            ugl_diff = 0.0
        else:
            match = False

        res_ugl.append({
            'ISIN': isin, 'Script Code': row.get('script_code', ''),
            'Closing Amount': agg_closing_amt, 'Expected MV': agg_expected_mv,
            'Calculated UGL': calc_ugl, 'Input UGL': agg_input_ugl,
            'UGL Diff': ugl_diff, 'UGL Match': match
        })

        if not match:
            # We add to exceptions
            pass

    df_ugl = pd.DataFrame(res_ugl)

    ugl_exc = []
    for _, row in df_ugl.iterrows():
        if not row['UGL Match']:
            ugl_exc.append({'ISIN': row['ISIN'], 'Script': row['Script Code'], 'Issue': 'UGL Mismatch', 'Details': f"Calc: {row['Calculated UGL']}, Input: {row['Input UGL']}"})

    if ugl_exc:
        df_exceptions = pd.concat([df_exceptions, pd.DataFrame(ugl_exc)], ignore_index=True)

    summary = {
        'Total ISINs (Agg)': len(shares_agg),
        'Closing Units Mismatches': len(df_closing[~df_closing['Port Match']]),
        'Closing Amount Mismatches': len(df_amount[~df_amount['Match']]),
        'Bonus Mismatches': len(df_bonus[~df_bonus['Match']]),
        'Dividend Mismatches': len(df_dividend[~df_dividend['Match']]),
        'MV/Price Mismatches': len(df_price_mv[~df_price_mv['MV Match']]),
        'UGL Mismatches': len(df_ugl[~df_ugl['UGL Match']])
    }

    output_dfs = {
        'Closing Units': df_closing,
        'Closing Amount': df_amount,
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
        workbook = writer.book
        pct_fmt = workbook.add_format({'num_format': '0.00%'})
        num_fmt = workbook.add_format({'num_format': '#,##0.00'})

        def write(df, name):
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)
                worksheet = writer.sheets[name]
                for i, col in enumerate(df.columns):
                    if col == 'MV Diff %':
                        worksheet.set_column(i, i, None, pct_fmt)
                    elif 'Price' in col or 'MV' in col or 'Diff' in col or 'Amount' in col or 'UGL' in col or 'Units' in col:
                        worksheet.set_column(i, i, None, num_fmt)
            else:
                pd.DataFrame().to_excel(writer, sheet_name=name, index=False)

        write(output_dfs.get('Closing Units'), 'Closing Units Verification')
        write(output_dfs.get('Closing Amount'), 'Closing Amount Verification')
        write(output_dfs.get('Bonus'), 'Bonus Verification')
        write(output_dfs.get('Dividend'), 'Dividend Working')
        write(output_dfs.get('Price_MV'), 'Market Price & MV Verification')
        write(output_dfs.get('UGL'), 'UGL Verification')
        write(df_exceptions, 'Exception Report')

    return output.getvalue()
