from bs4 import BeautifulSoup
import pandas as pd
import re

def parse_portfolio_html(file_obj):
    """
    Parses the Portfolio HTML file.
    file_obj: UploadedFile object or file path.
    """
    try:
        if hasattr(file_obj, 'read'):
            content = file_obj.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
        else:
            with open(file_obj, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

        soup = BeautifulSoup(content, 'lxml')
    except Exception as e:
        return None, f"Error parsing HTML: {str(e)}"

    data = []

    # Strategy: Find all tables, look for headers ISIN and Closing Balance
    # Then extract rows.
    # Handle "No transactions" section similarly.

    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        if not rows:
            continue

        # Try to identify columns from header row
        # Usually first row or th
        header_map = {}
        header_found = False

        # Scan first few rows for header
        for i, row in enumerate(rows[:5]):
            cells = row.find_all(['th', 'td'])
            cell_texts = [c.get_text(strip=True).lower() for c in cells]

            if 'isin' in cell_texts and ('closing balance' in cell_texts or 'closing qty' in cell_texts or 'balance' in cell_texts):
                # Found header
                for idx, text in enumerate(cell_texts):
                    if 'isin' in text:
                        header_map['isin'] = idx
                    elif 'closing balance' in text or 'closing qty' in text or 'balance' in text:
                        # Prioritize explicit Closing Balance
                        header_map['closing'] = idx
                header_found = True
                start_row = i + 1
                break

        if header_found and 'isin' in header_map and 'closing' in header_map:
            # Extract data from this table
            for row in rows[start_row:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) <= max(header_map.values()):
                    continue

                isin_text = cells[header_map['isin']].get_text(strip=True)
                closing_text = cells[header_map['closing']].get_text(strip=True)

                # Check ISIN format
                if isin_text.upper().startswith('INE'):
                    # Clean closing balance
                    # Remove commas, verify number
                    closing_clean = re.sub(r'[^\d.]', '', closing_text)
                    try:
                        closing_val = float(closing_clean) if closing_clean else 0.0
                        data.append({
                            'isin': isin_text.upper(),
                            'portfolio_closing_units': closing_val
                        })
                    except ValueError:
                        continue

    if not data:
        # Fallback: Look for "No transactions recorded..." text and try to find a table following it
        # Sometimes these are just listed without strict headers in the same way
        # But if the main logic failed, we might need a more generic scraper
        return None, "No valid ISIN/Closing Balance data found in HTML tables."

    df = pd.DataFrame(data)
    # Aggregate if duplicates (shouldn't be for closing balance, but just in case take the last one or sum?)
    # Usually one entry per ISIN.
    df = df.drop_duplicates(subset=['isin'], keep='last')

    return df, None
