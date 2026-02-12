import pandas as pd
import re
import logging
from datetime import datetime

def process_corporate_actions(file, start_date, end_date):
    """
    Processes the Corporate Action CSV file to filter dividends and match dates.

    Args:
        file (file-like object or str): The CSV file object or path.
        start_date (datetime): The start date of the quarter.
        end_date (datetime): The end date of the quarter.

    Returns:
        pd.DataFrame: A DataFrame containing filtered and processed corporate actions.
    """
    logging.info("Starting corporate action processing.")

    try:
        df = pd.read_csv(file)
    except Exception as e:
        logging.error(f"Failed to read CSV file: {e}")
        return pd.DataFrame()

    # Columns expected: Security Code, Security Name, Company Name, Ex Date, Purpose, Record Date, Payment Date
    # We strip whitespace from column names just in case
    df.columns = df.columns.str.strip()

    required_columns = ['Security Code', 'Security Name', 'Ex Date', 'Purpose']

    # Check for missing columns
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        logging.error(f"Missing columns in CSV: {missing_cols}")
        return pd.DataFrame()

    # Filter for Dividends
    # Case insensitive search for "Dividend" in 'Purpose'
    df = df[df['Purpose'].str.contains("Dividend", case=False, na=False)].copy()

    if df.empty:
        logging.info("No dividend entries found in the file.")
        return pd.DataFrame()

    # Convert Ex Date to datetime
    # Try multiple formats if needed, but standard usually provided
    # Assuming DD-MM-YYYY or DD/MM/YYYY or similar. Pandas to_datetime is smart.
    # Note: In India, dates are often DD-MM-YYYY
    try:
        df['Ex Date'] = pd.to_datetime(df['Ex Date'], dayfirst=True)
    except Exception as e:
        logging.error(f"Date conversion failed: {e}")
        # If conversion fails for some rows, convert errors='coerce' to get NaT
        df['Ex Date'] = pd.to_datetime(df['Ex Date'], dayfirst=True, errors='coerce')
        # Filter out invalid dates
        df = df.dropna(subset=['Ex Date']).copy()

    # Filter by date range
    # Ensure start_date and end_date are timestamps to compare with df['Ex Date']
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    df = df[(df['Ex Date'] >= start_ts) & (df['Ex Date'] <= end_ts)].copy()

    if df.empty:
        logging.info(f"No dividends found in the date range {start_date} to {end_date}.")
        return df

    # Extract DPS
    def extract_dps(purpose_text):
        if not isinstance(purpose_text, str):
            return None
        # Pattern: look for "Rs. - <amount>" or just number after some text
        # Example: "Interim Dividend - Rs. - 2.5000"
        # Regex to find a float number

        # We look for "Rs." followed optionally by "-" then the number
        match = re.search(r'(?:Rs\.?|INR)\s*-?\s*([\d\.]+)', purpose_text, re.IGNORECASE)
        if match:
            val_str = match.group(1).rstrip('.') # remove trailing dot if any
            try:
                return float(val_str)
            except ValueError:
                pass

        # Fallback: sometimes it's just "Dividend - 2.50"
        match = re.search(r'Dividend\s*-\s*([\d\.]+)', purpose_text, re.IGNORECASE)
        if match:
            val_str = match.group(1).rstrip('.')
            try:
                return float(val_str)
            except ValueError:
                pass

        return None

    df['DPS'] = df['Purpose'].apply(extract_dps)

    # Log rows where DPS could not be extracted
    # We might want to keep them in exception report later,
    # but for now we keep them in the DF with NaN DPS so the engine can flag them.

    logging.info(f"Processed {len(df)} corporate actions.")
    return df
