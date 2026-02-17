import pandas as pd
import logging

def parse_bhav_copy(file):
    """
    Parses the NSE Bhav Copy CSV.

    Extracts:
    - ISIN
    - CLOSE (Market Price)

    Args:
        file: CSV file object.

    Returns:
        pd.DataFrame: Columns ['ISIN', 'CLOSE']
    """
    logging.info("Starting Bhav Copy parsing.")

    try:
        df = pd.read_csv(file)

        # Clean column names
        df.columns = df.columns.str.strip().str.upper()

        # Find required columns
        isin_col = None
        close_col = None

        for col in df.columns:
            if col == 'ISIN':
                isin_col = col
            elif col == 'CLOSE':
                close_col = col

        if not isin_col or not close_col:
            raise ValueError(f"Missing columns in Bhav Copy. Found: {df.columns.tolist()}. Required: ISIN, CLOSE.")

        # Select and Filter
        final_df = df[[isin_col, close_col]].copy()
        final_df.rename(columns={isin_col: 'ISIN', close_col: 'CLOSE'}, inplace=True)

        # Clean Data
        final_df['CLOSE'] = pd.to_numeric(final_df['CLOSE'], errors='coerce')
        final_df = final_df.dropna(subset=['ISIN', 'CLOSE'])

        # Filter duplicates (keep last? Bhav copy usually has unique ISIN for EQ series, but might have others)
        # Assuming we want EQ series mostly, but ISIN is unique per security.
        # If duplicates exist for ISIN, we take the one with higher price? Or first?
        # Usually ISIN is unique in the final bhavcopy for Equity.
        final_df = final_df.drop_duplicates(subset=['ISIN'], keep='last')

        return final_df

    except Exception as e:
        logging.error(f"Error parsing Bhav Copy: {e}")
        return pd.DataFrame()
