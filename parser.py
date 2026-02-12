from bs4 import BeautifulSoup
import pandas as pd
import logging
import re

def parse_portfolio_html(file_content):
    """
    Parses the Portfolio HTML file to extract ISIN, Script Name, and Closing Quantity.

    Args:
        file_content (str): The HTML content of the portfolio file.

    Returns:
        pd.DataFrame: A DataFrame containing 'ISIN', 'Script Name', 'Closing Quantity'.
    """
    logging.info("Starting portfolio HTML parsing.")
    soup = BeautifulSoup(file_content, 'lxml')

    data = []

    # Locate all tables
    # The structure provided says:
    # Each investment block starts with:
    # <table border="1">
    # ISIN | <ISIN VALUE> | <SCRIPT NAME>

    tables = soup.find_all('table')

    # We iterate through tables and look for the specific header pattern
    for table in tables:
        rows = table.find_all('tr')
        if not rows:
            continue

        # Check the first row for ISIN marker
        first_row_cells = rows[0].find_all(['td', 'th'])
        if len(first_row_cells) < 3:
            continue

        first_cell_text = first_row_cells[0].get_text(strip=True)

        if "ISIN" in first_cell_text:
            isin = first_row_cells[1].get_text(strip=True)
            script_name = first_row_cells[2].get_text(strip=True)

            closing_qty = None

            # Find the closing balance
            # It could be "Closing Balance :" or just "Balance :"
            # The value is usually in the last cell of that row

            found_balance = False

            # Iterate backwards through rows to find the balance
            for row in reversed(rows):
                cells = row.find_all(['td', 'th'])
                row_text = row.get_text(" ", strip=True)

                # Check for label
                if "Closing Balance" in row_text or "Balance :" in row_text:
                    # The value is likely in the last cell
                    if cells:
                        last_cell_text = cells[-1].get_text(strip=True)
                        # Clean up value (remove commas)
                        clean_value = last_cell_text.replace(',', '').strip()
                        try:
                            closing_qty = float(clean_value)
                            found_balance = True
                            break
                        except ValueError:
                            # Try the second to last cell if last one is empty or not a number
                            if len(cells) > 1:
                                second_last_text = cells[-2].get_text(strip=True).replace(',', '').strip()
                                try:
                                    closing_qty = float(second_last_text)
                                    found_balance = True
                                    break
                                except ValueError:
                                    pass

            if found_balance:
                data.append({
                    'ISIN': isin,
                    'Script Name': script_name,
                    'Closing Quantity': closing_qty
                })
            else:
                logging.warning(f"Could not find closing quantity for ISIN: {isin}")

    df = pd.DataFrame(data)

    # Duplicate ISIN check
    if not df.empty:
        if df['ISIN'].duplicated().any():
            duplicates = df[df['ISIN'].duplicated()]['ISIN'].unique().tolist()
            logging.warning(f"Duplicate ISINs found: {duplicates}")

    logging.info(f"Parsed {len(df)} records from portfolio.")
    return df
