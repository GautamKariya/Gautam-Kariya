import pandas as pd
from bs4 import BeautifulSoup
import re
import logging

def parse_portfolio_html_v2(file_content):
    """
    Parses the NSDL/SHCIL Portfolio Transaction Statement HTML.

    Structure:
    - Section 1: ISINs with Transactions (ends with specific separator).
    - Section 2: ISINs with No Transactions (starts after separator).

    Extracts:
    - ISIN (Must start with 'INE', ignore 'INF')
    - Script Name
    - Final Closing Balance Quantity

    Args:
        file_content (str): HTML content.

    Returns:
        pd.DataFrame: Columns ['ISIN', 'Script Name', 'Closing Quantity']
    """
    logging.info("Starting Portfolio HTML parsing (v2).")
    soup = BeautifulSoup(file_content, 'lxml')

    data = []

    # The separator text that divides Section 1 and Section 2
    separator_text = "No transactions recorded for the following ISINs"

    tables = soup.find_all('table')

    current_isin = None
    current_script = None
    current_qty = None

    section = 1

    for table in tables:
        table_text = table.get_text(" ", strip=True)

        # Check Separator
        if separator_text.lower() in table_text.lower():
            logging.info("Found separator. Switching to Section 2.")
            # Save pending from Section 1
            if current_isin and current_qty is not None:
                data.append({
                    'ISIN': current_isin,
                    'Script Name': current_script,
                    'Closing Quantity': current_qty
                })
            current_isin = None
            current_script = None
            current_qty = None
            section = 2
            continue

        rows = table.find_all('tr')
        if not rows:
            continue

        for row in rows:
            cells = row.find_all(['td', 'th'])
            row_text = row.get_text(" ", strip=True)

            # 1. Check for ISIN Header (Common to both sections)
            if len(cells) >= 3 and "ISIN" in cells[0].get_text(strip=True):
                 # Save previous
                if current_isin and current_qty is not None:
                    data.append({
                        'ISIN': current_isin,
                        'Script Name': current_script,
                        'Closing Quantity': current_qty
                    })

                # Start new
                raw_isin = cells[1].get_text(strip=True)
                raw_script = cells[2].get_text(strip=True)

                if raw_isin.startswith("INE"):
                    current_isin = raw_isin
                    current_script = raw_script
                    current_qty = None
                else:
                    current_isin = None

                continue

            # 2. Check for Balance Row (Common to both sections)
            if current_isin:
                # Look for "Closing Balance" or "Balance"
                if "Closing Balance" in row_text or "Balance" in row_text:
                    # Extract numeric value using regex from the row or last cell
                    # This handles both Section 1 (Value in separate cell) and Section 2 (Value in same cell text)

                    # Try last cell text first (most likely location)
                    target_text = ""
                    if cells:
                        target_text = cells[-1].get_text(strip=True)
                    else:
                        target_text = row_text # Fallback to whole row

                    # Remove commas
                    clean_text = target_text.replace(',', '')

                    # Regex to find a number (integer or float)
                    # Pattern: optional - sign, digits, optional dot, optional digits
                    match = re.search(r'([-+]?\d*\.?\d+)', clean_text)

                    if match:
                        try:
                            val = float(match.group(1))
                            current_qty = val
                        except ValueError:
                            pass

    # Save last entry
    if current_isin and current_qty is not None:
         data.append({
            'ISIN': current_isin,
            'Script Name': current_script,
            'Closing Quantity': current_qty
        })

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=['ISIN'], keep='last')

    logging.info(f"Parsed {len(df)} ISINs from Portfolio (v2).")
    return df
