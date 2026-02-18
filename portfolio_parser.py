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
            # Check if file object supports seek and reset it
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
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
    current_isin = None

    # Use find_all('tr') to iterate through all rows
    rows = soup.find_all('tr')

    for row in rows:
        # Get all cells in this row
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue

        cell_texts = [c.get_text(strip=True) for c in cells]

        # 1. Detect ISIN Row
        # Logic: Cell contains 'ISIN' and adjacent cell has value starting with 'IN'
        isin_found_in_row = False

        for i, txt in enumerate(cell_texts):
            if txt.upper() == 'ISIN':
                # Check next cell for value
                if i + 1 < len(cell_texts):
                    val = cell_texts[i+1].strip()
                    # Basic validation: starts with 'IN' (usually INE or INF) and length > 5
                    if len(val) > 5 and val.upper().startswith('IN'):
                        current_isin = val.upper()
                        isin_found_in_row = True
                        break

        if isin_found_in_row:
            continue

        # 2. Detect Balance Row (only if we have an active ISIN)
        if current_isin:
            balance_found = False
            balance_val = 0.0

            for i, txt in enumerate(cell_texts):
                txt_upper = txt.upper()

                # Exclude Opening
                if "OPENING" in txt_upper:
                    continue

                # Match Balance keywords
                # Note: "Balance :" includes the colon. "Closing Balance :" includes colon.
                # The user requirement: "Balance :" (transaction) or "Closing Balance :" (no transaction)

                if "BALANCE :" in txt_upper or "CLOSING BALANCE :" in txt_upper:
                    # Found label.

                    # Strategy A: Value is in the NEXT cell
                    if i + 1 < len(cell_texts):
                        val_str = cell_texts[i+1]
                        # Remove commas, keep digits and dot
                        val_clean = re.sub(r'[^\d.]', '', val_str)
                        try:
                            # Verify if clean string is non-empty
                            if val_clean:
                                balance_val = float(val_clean)
                                balance_found = True
                        except ValueError:
                            pass

                    # Strategy B: Value is embedded in the label cell text? (Unlikely per snippet, but robust)
                    if not balance_found:
                         matches = re.findall(r'(\d+(?:\.\d+)?)', txt)
                         if matches:
                             try:
                                 balance_val = float(matches[-1])
                                 balance_found = True
                             except ValueError:
                                 pass

                    if balance_found:
                        # Add record
                        data.append({
                            'isin': current_isin,
                            'portfolio_closing_units': balance_val
                        })
                        current_isin = None # Reset for next ISIN block
                        break

    if not data:
        return None, "No valid ISIN/Closing Balance data found in HTML."

    df = pd.DataFrame(data)

    # Filter for Equity Shares (INE)
    # The snippet contained INF (Mutual Funds), we filter them out here as per requirement
    df_ine = df[df['isin'].str.startswith('INE')].copy()

    # Drop duplicates if any (keep last entry per ISIN just in case)
    df_ine = df_ine.drop_duplicates(subset=['isin'], keep='last')

    return df_ine, None
