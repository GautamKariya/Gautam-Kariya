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
            # Group 1 = New (A), Group 2 = Old (B)
            # Interpretation: A:B -> A new shares for B old shares
            # Ratio = A / B
            match = re.search(r'(\d+)\s*:\s*(\d+)', purpose)
            if match:
                try:
                    new_share_a = float(match.group(1))
                    old_share_b = float(match.group(2))
                    if old_share_b > 0:
                        ratio = new_share_a / old_share_b
                        results.append({
                            'script_code': script_code,
                            'ex_date': ex_date,
                            'action_type': 'Bonus',
                            'value': ratio,
                            'details': f"Bonus {int(new_share_a)}:{int(old_share_b)}"
                        })
                except ValueError:
                    pass

        # Dividend Logic
        elif "dividend" in purpose_lower:
            # Must contain "Dividend" (already checked by elif condition, but double check)
            # Ignore Bonus rows if they happen to contain "Dividend" word (unlikely but safe)
            if "bonus" in purpose_lower:
                continue

            # Extract DPS
            # User requirement: Extract numeric value after "Rs."
            # Regex: Rs\.?\s*(\d+(?:\.\d+)?)

            dps = 0.0
            found_dps = False

            # Try specific currency patterns first
            curr_match = re.search(r'(?:rs\.?|inr)\s*-?\s*(\d+(?:\.\d+)?)', purpose, re.IGNORECASE)
            if curr_match:
                try:
                    dps = float(curr_match.group(1))
                    found_dps = True
                except ValueError:
                    pass
            else:
                # Fallback: find first number found (if strict "Rs." requirement fails?)
                # User said: "Extract DPS value after: Rs. Use regex to extract the numeric value."
                # But previous prompt said "Primary pattern expected: Rs., Rs, INR or no prefix."
                # Current prompt says "Extract DPS value after: Rs."
                # I will stick to looking for Rs/INR first, then fallback to first number if no Rs found?
                # "2. Extract DPS value after: Rs." -> implies Rs is present.
                # But let's be robust. If "Dividend 2.50", it's likely 2.50.

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
