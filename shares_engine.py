import pandas as pd
import logging

def verify_shares_audit(portfolio_df, client_df, corporate_actions_df, bhav_copy_df):
    """
    Performs the 6-Step Shares Audit Verification.

    1. Closing Units Verification (Portfolio vs Client)
    2. Bonus Verification (Corp Action vs Client)
    3. Dividend Verification (Corp Action vs Client)
    4. Market Price Verification (Bhav Copy vs Client)
    5. Market Value Verification (Calculated vs Client)
    6. UGL Verification (Calculated vs Client)

    Args:
        portfolio_df: DataFrame (ISIN, Script Name, Closing Quantity)
        client_df: DataFrame (Script Code, ISIN, Closing Units, Closing Amount, Market Price, Market Value, UGL, Dividend Received, Bonus Received)
        corporate_actions_df: DataFrame (Script Code, Ex Date, Purpose, DPS, Bonus Ratio)
        bhav_copy_df: DataFrame (ISIN, CLOSE)

    Returns:
        tuple: (reconciliation_summary, detailed_exceptions, working_paper_dict)
    """
    logging.info("Starting Shares Audit Verification.")

    # Dictionaries for faster lookups
    port_map = portfolio_df.set_index('ISIN').to_dict('index')

    # Corp Actions: Group by Script Code
    # Need to handle multiple actions for same script
    # Standardize Script Code to string for robust grouping
    corporate_actions_df = corporate_actions_df.copy()
    try:
        corporate_actions_df['Script Code'] = corporate_actions_df['Script Code'].astype(float).astype(int).astype(str)
    except ValueError:
        corporate_actions_df['Script Code'] = corporate_actions_df['Script Code'].astype(str)

    corp_groups = corporate_actions_df.groupby('Script Code')

    bhav_map = bhav_copy_df.set_index('ISIN')['CLOSE'].to_dict()

    exceptions = []

    # Results for Working Paper sheets
    wp_closing = []
    wp_bonus = []
    wp_dividend = []
    wp_price = []
    wp_mv_ugl = []

    for idx, row in client_df.iterrows():
        isin = str(row['ISIN']).strip()
        script_code = str(row['Script Code']).strip()
        # Clean Script Code to match group keys
        try:
             clean_script_code = str(int(float(script_code)))
        except ValueError:
             clean_script_code = script_code

        # Client Values
        client_units = float(row['Closing Units'])
        client_amt = float(row['Closing Amount'])
        client_price = float(row['Market Price'])
        client_mv = float(row['Market Value'])
        client_ugl = float(row['UGL'])
        client_div = float(row['Dividend Received'])
        client_bonus = float(row['Bonus Received'])

        # 1. Closing Units Verification
        port_data = port_map.get(isin)
        port_units = port_data['Closing Quantity'] if port_data else 0.0

        diff_units = client_units - port_units
        status_units = "Matched" if abs(diff_units) < 0.01 else "Mismatch"

        if status_units == "Mismatch":
             exceptions.append({
                'Script Code': clean_script_code,
                'ISIN': isin,
                'Check Type': 'Closing Units',
                'Expected Value': port_units,
                'Input Value': client_units,
                'Difference': diff_units
            })

        wp_closing.append({
            'ISIN': isin,
            'Script Code': clean_script_code,
            'Portfolio Units': port_units,
            'Client Units': client_units,
            'Difference': diff_units,
            'Status': status_units
        })

        # Get Corporate Actions for this Script
        # Check type alignment for dictionary lookup
        # corp_groups keys might be int64. clean_script_code is str.
        # We need to check both or standardize.
        # Let's iterate or assume standardization in parser.
        # Best to try converting key to str for lookup if possible?
        # Actually, let's just standardize corp_groups keys to str in a map
        # But we can't easily re-index a groupby object.
        # We'll do a quick check.

        # Efficient way:
        # Filter corp actions for this script
        # Assuming script codes in CSV are int-like

        # We'll filter the original DF or use a pre-built dict of list of dicts
        # Let's do that at the start? No, loop is fine if not huge.
        # Better: Pre-process corp actions into a dict: ScriptCode(str) -> List of rows

        # 2. Bonus Verification
        # Find Bonus Actions
        expected_bonus = 0.0
        bonus_details = []

        # Fetch Corporate Actions for this script
        script_actions = pd.DataFrame()
        if clean_script_code in corp_groups.groups:
             script_actions = corp_groups.get_group(clean_script_code)

        # Process Actions
        total_expected_div = 0.0
        div_details = []

        if not script_actions.empty:
            for _, action in script_actions.iterrows():
                # Bonus
                # Check if Bonus Ratio is not None (it might be NaN if not a bonus row)
                if pd.notna(action['Bonus Ratio']):
                    a, b = action['Bonus Ratio']
                    if a > 0:
                        # Calculation Logic:
                        # Bonus is given on existing shares.
                        # Total Shares = Original Shares + Bonus Shares
                        # Bonus Shares = Original Shares * (B/A)
                        # We have Closing Shares (Total). We have Client Bonus.
                        # We need to verify if Client Bonus matches Expected Bonus based on implied Original.
                        # Implied Original = Closing - Client Bonus (Assuming Client Bonus is correct? Or recursive?)
                        # Standard Audit: Verify if Client Bonus is mathematically consistent with Closing?
                        # Or verify if Closing is consistent with Opening?
                        # The prompt says: "Expected Bonus Units = Opening Units * (B/A)"
                        # "Verify Expected Bonus Units vs Bonus Units column in Shares Input File".
                        # This implies we derive Expected from Opening.
                        # Since we don't have Opening column, we infer: Opening = Closing - Bonus (from client).
                        # So we check if (Closing - Bonus) * Ratio == Bonus.

                        pre_bonus_qty = client_units - client_bonus
                        calc_bonus = pre_bonus_qty * (b / a)
                        expected_bonus += calc_bonus
                        bonus_details.append(f"Bonus {a}:{b}")

                # Dividend
                dps = action['DPS']
                if dps > 0:
                     # Expected Div = Closing Units * DPS
                     total_expected_div += client_units * dps
                     div_details.append(f"DPS {dps} ({action['Purpose']})")

        # Bonus Check
        diff_bonus = client_bonus - expected_bonus
        status_bonus = "Matched" if abs(diff_bonus) < 0.01 else "Mismatch"

        if status_bonus == "Mismatch":
             exceptions.append({
                'Script Code': clean_script_code,
                'ISIN': isin,
                'Check Type': 'Bonus',
                'Expected Value': expected_bonus,
                'Input Value': client_bonus,
                'Difference': diff_bonus
            })

        wp_bonus.append({
            'ISIN': isin,
            'Script Code': clean_script_code,
            'Corp Action': ", ".join(bonus_details),
            'Expected Bonus': expected_bonus,
            'Client Bonus': client_bonus,
            'Difference': diff_bonus,
            'Status': status_bonus
        })

        # 3. Dividend Check
        diff_div = client_div - total_expected_div
        status_div = "Matched" if abs(diff_div) < 1.0 else "Mismatch" # Allow small rounding diff

        if status_div == "Mismatch":
             exceptions.append({
                'Script Code': clean_script_code,
                'ISIN': isin,
                'Check Type': 'Dividend',
                'Expected Value': total_expected_div,
                'Input Value': client_div,
                'Difference': diff_div
            })

        wp_dividend.append({
            'ISIN': isin,
            'Script Code': clean_script_code,
            'Details': ", ".join(div_details),
            'Expected Dividend': total_expected_div,
            'Client Dividend': client_div,
            'Difference': diff_div,
            'Status': status_div
        })

        # 4. Market Price Verification
        # Bhav Copy Lookup
        bhav_price = bhav_map.get(isin, 0.0)

        diff_price = client_price - bhav_price

        # Logic: Compare Input File Market Price vs Bhav CLOSE
        # Allow small tolerance
        status_price = "Matched" if abs(diff_price) < 0.05 else "Mismatch"

        if status_price == "Mismatch":
             exceptions.append({
                'Script Code': clean_script_code,
                'ISIN': isin,
                'Check Type': 'Market Price',
                'Expected Value': bhav_price,
                'Input Value': client_price,
                'Difference': diff_price
            })

        wp_price.append({
            'ISIN': isin,
            'Script Code': clean_script_code,
            'Bhav Copy Price': bhav_price,
            'Client Price': client_price,
            'Difference': diff_price,
            'Status': status_price
        })

        # 5. Market Value Verification
        # Expected Market Value = Market Price (Bhav) * Closing Units
        expected_mv = bhav_price * client_units
        diff_mv = client_mv - expected_mv
        status_mv = "Matched" if abs(diff_mv) < 1.0 else "Mismatch"

        if status_mv == "Mismatch":
             exceptions.append({
                'Script Code': clean_script_code,
                'ISIN': isin,
                'Check Type': 'Market Value',
                'Expected Value': expected_mv,
                'Input Value': client_mv,
                'Difference': diff_mv
            })

        # 6. UGL Verification
        # Expected UGL = Market Value (Bhav) - Closing Amount (Cost)
        expected_ugl = expected_mv - client_amt
        diff_ugl = client_ugl - expected_ugl
        status_ugl = "Matched" if abs(diff_ugl) < 1.0 else "Mismatch"

        if status_ugl == "Mismatch":
             exceptions.append({
                'Script Code': clean_script_code,
                'ISIN': isin,
                'Check Type': 'UGL',
                'Expected Value': expected_ugl,
                'Input Value': client_ugl,
                'Difference': diff_ugl
            })

        wp_mv_ugl.append({
            'ISIN': isin,
            'Script Code': clean_script_code,
            'Closing Amount (Cost)': client_amt,
            'Audited MV': expected_mv,
            'Client MV': client_mv,
            'Expected UGL': expected_ugl,
            'Client UGL': client_ugl,
            'Diff MV': diff_mv,
            'Diff UGL': diff_ugl,
            'Status': "Mismatch" if (status_mv=="Mismatch" or status_ugl=="Mismatch") else "Matched"
        })

    # Summary
    # Group exceptions by Script Code to count
    summary_data = []
    scripts = client_df['Script Code'].unique()
    for sc in scripts:
        sc_str = str(sc)
        # Count exceptions for this script
        count = len([e for e in exceptions if str(e['Script Code']) == str(int(float(sc)))])
        # (Handling the float/int/str mess slightly inefficiently but safely)

        status = "OK" if count == 0 else "Exceptions Found"
        summary_data.append({
            'Script Code': sc,
            'Status': status,
            'No. of Exceptions': count
        })

    return (
        pd.DataFrame(summary_data),
        pd.DataFrame(exceptions),
        {
            'Closing Units': pd.DataFrame(wp_closing),
            'Bonus': pd.DataFrame(wp_bonus),
            'Dividend': pd.DataFrame(wp_dividend),
            'Market Price': pd.DataFrame(wp_price),
            'MV & UGL': pd.DataFrame(wp_mv_ugl)
        }
    )
