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
    # Case-insensitive mapping
    col_map = {c.lower(): c for c in df.columns}

    final_cols = {}
    for rc in req_cols:
        if rc.lower() in col_map:
            final_cols[rc] = col_map[rc.lower()]

    if len(final_cols) < len(req_cols):
        missing = [rc for rc in req_cols if rc.lower() not in col_map]
        return None, f"Missing columns in Corporate Action CSV: {', '.join(missing)}"

    # Rename to standard
    df = df.rename(columns={v: k for k, v in final_cols.items()})

    # Convert Ex Date to datetime
    # Use pandas robust parsing, assuming dayfirst for Indian context
    df['Ex Date'] = pd.to_datetime(df['Ex Date'], dayfirst=True, errors='coerce').dt.date

    # Filter by date range
    # Ensure inputs are dates
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
            # Regex: (\d+)\s*:\s*(\d+)
            # Group 1 = Old (A), Group 2 = New (B)
            # Ratio = New / Old = B / A
            match = re.search(r'(\d+)\s*:\s*(\d+)', purpose)
            if match:
                try:
                    old_share = float(match.group(1))
                    new_share = float(match.group(2))
                    if old_share > 0:
                        ratio = new_share / old_share
                        results.append({
                            'script_code': script_code,
                            'ex_date': ex_date,
                            'action_type': 'Bonus',
                            'value': ratio,
                            'details': f"Bonus {int(old_share)}:{int(new_share)}"
                        })
                except ValueError:
                    pass

        # Dividend Logic
        elif any(k in purpose_lower for k in ["interim dividend", "final dividend", "special dividend"]):
            # Extract DPS
            dps = 0.0
            found_dps = False

            # Try specific currency patterns first
            curr_match = re.search(r'(?:rs\.?|inr)\s*(\d+(?:\.\d+)?)', purpose, re.IGNORECASE)
            if curr_match:
                try:
                    dps = float(curr_match.group(1))
                    found_dps = True
                except ValueError:
                    pass
            else:
                # Fallback: find first number found.
                nums = re.findall(r'(\d+(?:\.\d+)?)', purpose)
                if nums:
                    try:
                         dps = float(nums[0])
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

    # Return DataFrame
    if not results:
        # Return empty DF with columns
        return pd.DataFrame(columns=['script_code', 'ex_date', 'action_type', 'value', 'details']), None

    return pd.DataFrame(results), None
