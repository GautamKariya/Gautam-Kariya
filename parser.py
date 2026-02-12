import pandas as pd
from bs4 import BeautifulSoup
import re
import logging

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

    current_isin = None
    current_script = None
    current_qty = None

    # Locate all tables
    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        if not rows:
            continue

        first_row_cells = rows[0].find_all(['td', 'th'])
        if not first_row_cells:
            continue

        first_cell_text = first_row_cells[0].get_text(strip=True)

        # Check for ISIN Header Table
        if "ISIN" == first_cell_text and len(first_row_cells) >= 3:

            # Save previous record if valid
            if current_isin:
                if current_qty is not None:
                     data.append({
                        'ISIN': current_isin,
                        'Script Name': current_script,
                        'Closing Quantity': current_qty
                    })
                else:
                     logging.warning(f"No closing balance found for ISIN: {current_isin}")

            # Start new record
            current_isin = first_row_cells[1].get_text(strip=True)
            current_script = first_row_cells[2].get_text(strip=True)
            current_qty = None
            continue

        # Check for Balance Table associated with current ISIN
        if current_isin:
            for row in rows:
                cells = row.find_all(['td', 'th'])
                row_text = row.get_text(" ", strip=True)

                # Check for "Closing Balance :" or "Balance :"
                # Be robust about whitespace
                if "Closing Balance" in row_text or "Balance :" in row_text:
                    if cells:
                        val_text = cells[-1].get_text(strip=True).replace(',', '')
                        try:
                            # Update current_qty.
                            # We take the float value.
                            current_qty = float(val_text)
                        except ValueError:
                             pass

    # Save the last record after loop finishes
    if current_isin and current_qty is not None:
        data.append({
            'ISIN': current_isin,
            'Script Name': current_script,
            'Closing Quantity': current_qty
        })

    df = pd.DataFrame(data)

    # Duplicate ISIN check
    if not df.empty:
        if df['ISIN'].duplicated().any():
            duplicates = df[df['ISIN'].duplicated()]['ISIN'].unique().tolist()
            logging.warning(f"Duplicate ISINs found: {duplicates}")

    logging.info(f"Parsed {len(df)} records from portfolio.")
    return df
