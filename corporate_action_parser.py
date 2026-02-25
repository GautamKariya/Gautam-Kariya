import pandas as pd
import re
from datetime import datetime, date

def parse_corporate_action(file_obj, start_date, end_date):
    """
    Parses Corporate Action CSV.
    file_obj: UploadedFile or path.
    start_date, end_date: datetime.date objects.
    """
    try:
        df = pd.read_csv(file_obj)
    except Exception as e:
        return None, f"Error reading CSV: {str(e)}"

    # Standardize column names
    df.columns = [str(c).strip() for c in df.columns]

    # Required columns check
    req_cols = ['Security Code', 'Purpose', 'Ex Date']
    col_map = {c.lower(): c for c in df.columns}

    final_cols = {}
    for rc in req_cols:
        if rc.lower() in col_map:
            final_cols[rc] = col_map[rc.lower()]

    if len(final_cols) < len(req_cols):
        missing = [rc for rc in req_cols if rc.lower() not in col_map]
        return None, f"Missing columns in Corporate Action CSV: {', '.join(missing)}"

    df = df.rename(columns={v: k for k, v in final_cols.items()})

    # Convert Ex Date to datetime
    df['Ex Date'] = pd.to_datetime(df['Ex Date'], dayfirst=True, errors='coerce').dt.date

    # Filter by date range
    if isinstance(start_date, datetime): start_date = start_date.date()
    if isinstance(end_date, datetime): end_date = end_date.date()

    df = df.dropna(subset=['Ex Date'])
    df = df[(df['Ex Date'] >= start_date) & (df['Ex Date'] <= end_date)]

    results = []

    for _, row in df.iterrows():
        purpose = str(row['Purpose']).strip()
        script_code = str(row['Security Code']).strip() # Ensure string for joining
        ex_date = row['Ex Date']

        purpose_lower = purpose.lower()

        # Bonus Logic
        if "bonus issue" in purpose_lower:
            # Format: A:B -> A = Old, B = New (User specified)
            # Formula: Bonus = Opening * (New / Old) = Opening * (B / A)
            match = re.search(r'(\d+)\s*:\s*(\d+)', purpose)
            if match:
                try:
                    share_a_old = float(match.group(1))
                    share_b_new = float(match.group(2))
                    if share_a_old > 0:
                        ratio = share_b_new / share_a_old
                        results.append({
                            'script_code': script_code,
                            'ex_date': ex_date,
                            'action_type': 'Bonus',
                            'value': ratio,
                            'details': f"Bonus {int(share_a_old)}:{int(share_b_new)} (Old:New)"
                        })
                except ValueError:
                    pass

        # Dividend Logic
        elif "dividend" in purpose_lower:
            # Ignore Bonus rows
            if "bonus" in purpose_lower:
                continue

            # Extract DPS
            dps = 0.0
            found_dps = False

            # Pattern 1: Strict "Rs. - 0.80"
            match = re.search(r'Rs\.?\s*-\s*(\d+(?:\.\d+)?)', purpose, re.IGNORECASE)
            if match:
                try:
                    dps = float(match.group(1))
                    found_dps = True
                except ValueError:
                    pass

            # Pattern 2: Fallback "Rs. 0.80" or "INR 0.80"
            if not found_dps:
                match = re.search(r'(?:Rs\.?|INR)\s*(\d+(?:\.\d+)?)', purpose, re.IGNORECASE)
                if match:
                    try:
                        dps = float(match.group(1))
                        found_dps = True
                    except ValueError:
                        pass

            if found_dps:
                results.append({
                    'script_code': script_code,
                    'ex_date': ex_date,
                    'action_type': 'Dividend',
                    'value': dps,
                    'details': f"Dividend DPS: {dps}"
                })

    if not results:
        return pd.DataFrame(columns=['script_code', 'ex_date', 'action_type', 'value', 'details']), None

    return pd.DataFrame(results), None
