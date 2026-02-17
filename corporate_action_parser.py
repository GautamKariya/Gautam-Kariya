import pandas as pd
import re
import logging
from datetime import datetime

def parse_corporate_actions_equity(file, start_date, end_date):
    """
    Parses the Corporate Action CSV file to filter dividends and bonus issues.

    Filters:
    - Date range (Ex Date between start_date and end_date).
    - Purpose containing "Dividend" or "Bonus".

    Extracts:
    - Script Code (Security Code)
    - Purpose
    - DPS (Dividend Per Share)
    - Bonus Ratio (A:B)

    Args:
        file: CSV file object.
        start_date: Quarter start date.
        end_date: Quarter end date.

    Returns:
        pd.DataFrame: Columns ['Script Code', 'Purpose', 'DPS', 'Bonus Ratio', 'Ex Date']
    """
    logging.info("Starting Corporate Action parsing (Equity Only).")

    try:
        df = pd.read_csv(file)
    except Exception as e:
        logging.error(f"Failed to read CSV file: {e}")
        return pd.DataFrame()

    df.columns = df.columns.str.strip()

    # Map 'Security Code' to 'Script Code'
    if 'Security Code' in df.columns:
        df.rename(columns={'Security Code': 'Script Code'}, inplace=True)

    required_columns = ['Script Code', 'Ex Date', 'Purpose']
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        logging.error(f"Missing columns in Corp Action CSV: {missing_cols}")
        return pd.DataFrame()

    # Convert Ex Date
    try:
        df['Ex Date'] = pd.to_datetime(df['Ex Date'], dayfirst=True, errors='coerce')
    except Exception:
        pass

    df = df.dropna(subset=['Ex Date'])

    # Filter by Date
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    df = df[(df['Ex Date'] >= start_ts) & (df['Ex Date'] <= end_ts)].copy()

    if df.empty:
        return pd.DataFrame()

    # Filter for Dividend or Bonus
    # "Interim Dividend", "Final Dividend", "Special Dividend", "Bonus issue", "Bonus"
    mask_dividend = df['Purpose'].str.contains("Dividend", case=False, na=False)
    mask_bonus = df['Purpose'].str.contains("Bonus", case=False, na=False)

    df = df[mask_dividend | mask_bonus].copy()

    # Parse DPS or Bonus Ratio
    def parse_values(row):
        purpose = str(row['Purpose'])
        dps = 0.0
        bonus_ratio = None # (A, B) tuple -> A shares get B bonus

        # Dividend Logic
        if "Dividend" in purpose:
            # Priority: 'Amount' column if exists
            if 'Amount' in row and pd.notna(row['Amount']):
                try:
                    dps = float(row['Amount'])
                except ValueError:
                    dps = 0.0
            else:
                # Regex extraction
                # "Interim Dividend - Rs. - 0.8000"
                match = re.search(r'(?:Rs\.?|INR)\s*-?\s*([\d\.]+)', purpose, re.IGNORECASE)
                if match:
                    try:
                        dps = float(match.group(1).rstrip('.'))
                    except ValueError:
                        pass
                else:
                    # Fallback "Dividend - 2.50"
                    match = re.search(r'Dividend\s*-\s*([\d\.]+)', purpose, re.IGNORECASE)
                    if match:
                        try:
                            dps = float(match.group(1).rstrip('.'))
                        except ValueError:
                            pass

        # Bonus Logic
        # "Bonus issue 1:1", "Bonus 3:1"
        # Pattern: (\d+)\s*:\s*(\d+) -> Ratio A:B
        # Interpretation: For A shares, get B bonus shares.
        # User said: "Bonus issue A:B -> For A shares -> B bonus shares"
        # Wait. Usually "1:1" means "1 share for every 1 held".
        # "3:1" usually means "3 shares for every 1 held" OR "1 share for every 3 held"?
        # User clarification: "Bonus issue A:B -> For every A shares -> B bonus shares"
        # User example: "Bonus issue 3:1 -> For 3 shares -> 1 bonus share".
        # So Ratio is (A, B). Expected Bonus = Units * (B/A).

        if "Bonus" in purpose:
            match = re.search(r'(\d+)\s*:\s*(\d+)', purpose)
            if match:
                try:
                    a = float(match.group(1))
                    b = float(match.group(2))
                    if a > 0:
                        bonus_ratio = (a, b)
                except ValueError:
                    pass

        return pd.Series([dps, bonus_ratio])

    df[['DPS', 'Bonus Ratio']] = df.apply(parse_values, axis=1)

    return df[['Script Code', 'Ex Date', 'Purpose', 'DPS', 'Bonus Ratio']]
