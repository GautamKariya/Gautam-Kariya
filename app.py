import streamlit as st
import pandas as pd
from datetime import date
import logging
import io

# Setup logging
logging.basicConfig(filename='audit_log.txt', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Imports
try:
    from parser import parse_portfolio_html
    from corporate_actions import process_corporate_actions
    from working_parser import parse_working_file
    from dividend_engine import calculate_dividends, reconcile_holdings
except ImportError:
    import sys
    import os
    sys.path.append(os.getcwd())
    from parser import parse_portfolio_html
    from corporate_actions import process_corporate_actions
    from working_parser import parse_working_file
    from dividend_engine import calculate_dividends, reconcile_holdings

st.set_page_config(page_title="Quarterly Investment & Corporate Action Audit Tool", layout="wide")

def main():
    st.title("Quarterly Investment & Corporate Action Audit Tool")

    st.sidebar.header("Input Parameters")

    # Date selection
    col1, col2 = st.sidebar.columns(2)
    with col1:
        today = date.today()
        default_start = date(today.year, 1, 1)
        start_date = st.sidebar.date_input("Quarter Start Date", default_start)
    with col2:
        default_end = date(today.year, 3, 31)
        end_date = st.sidebar.date_input("Quarter End Date", default_end)

    # File uploads
    st.sidebar.markdown("---")
    portfolio_file = st.sidebar.file_uploader("1. Upload NSDL/SHCIL Portfolio HTML", type=["html", "htm"])
    corporate_file = st.sidebar.file_uploader("2. Upload Corporate Action CSV", type=["csv"])
    working_file = st.sidebar.file_uploader("3. Upload Working File (Excel)", type=["xlsx", "xls"])

    if st.sidebar.button("Run Reconciliation"):
        if portfolio_file and corporate_file and working_file:
            st.info("Processing files...")

            try:
                # 1. Parse Portfolio HTML (for Closing Balance verification)
                portfolio_bytes = portfolio_file.read()
                try:
                    portfolio_content = portfolio_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    portfolio_content = portfolio_bytes.decode('latin-1')

                portfolio_df = parse_portfolio_html(portfolio_content)
                st.success(f"Parsed Portfolio HTML: {len(portfolio_df)} ISINs found.")

                # 2. Parse Working File Excel (for Script Code & Holdings)
                working_file_df = parse_working_file(working_file)
                if working_file_df.empty:
                    st.error("Failed to parse Working File or no data found in 'Shares' sheet.")
                    return
                st.success(f"Parsed Working File: {len(working_file_df)} Scripts found.")

                # 3. Process Corporate Actions (for Dividend/Bonus data)
                corporate_file.seek(0)
                corporate_df = process_corporate_actions(corporate_file, start_date, end_date)
                st.success(f"Processed Corporate Actions: {len(corporate_df)} Dividends/Bonuses found in selected quarter.")

                # 4. Run Reconciliation Logic

                # A. Reconcile Holdings (Working File vs Portfolio HTML)
                reconciliation_df = reconcile_holdings(portfolio_df, working_file_df)

                # B. Calculate Dividends (Working File vs Corporate Action CSV)
                dividend_df, exception_df = calculate_dividends(working_file_df, corporate_df)

                # Display Results
                st.subheader("Reconciliation Dashboard")

                tab1, tab2, tab3, tab4 = st.tabs(["Dividend Working", "Holdings Reconciliation", "Exceptions", "Source Data"])

                with tab1:
                    st.write("### Dividend Calculation (Based on Working File & Corp Actions)")
                    if not dividend_df.empty:
                        st.dataframe(dividend_df)
                        total_div = dividend_df['Expected Dividend'].sum()
                        st.metric("Total Expected Dividend", f"{total_div:,.2f}")
                    else:
                        st.info("No dividends expected for the matched holdings in this quarter.")

                with tab2:
                    st.write("### Holdings Reconciliation (Working File vs Portfolio HTML)")
                    st.write("Matches Script Name from Working File with NSDL Portfolio.")
                    if not reconciliation_df.empty:
                        # Highlight mismatches
                        def highlight_mismatch(row):
                            color = 'background-color: #ffcccc' if row['Status'] != 'Matched' else ''
                            return [color] * len(row)

                        st.dataframe(reconciliation_df.style.apply(highlight_mismatch, axis=1))

                        mismatch_count = len(reconciliation_df[reconciliation_df['Status'] != 'Matched'])
                        if mismatch_count > 0:
                            st.warning(f"Found {mismatch_count} discrepancies in holdings.")
                        else:
                            st.success("All holdings matched successfully!")
                    else:
                        st.info("No reconciliation data generated.")

                with tab3:
                    st.write("### Exception Report")
                    if not exception_df.empty:
                        st.dataframe(exception_df)
                    else:
                        st.success("No exceptions found.")

                with tab4:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write("#### NSDL Portfolio Data")
                        st.dataframe(portfolio_df)
                    with col_b:
                        st.write("#### Working File Data (Aggregated)")
                        st.dataframe(working_file_df)

                # 5. Generate Excel Report
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    if not dividend_df.empty:
                        dividend_df.to_excel(writer, sheet_name='Dividend Working', index=False)
                    if not reconciliation_df.empty:
                        reconciliation_df.to_excel(writer, sheet_name='Holdings Reconciliation', index=False)
                    if not exception_df.empty:
                        exception_df.to_excel(writer, sheet_name='Exceptions', index=False)
                    if not portfolio_df.empty:
                        portfolio_df.to_excel(writer, sheet_name='Source - NSDL', index=False)
                    if not working_file_df.empty:
                        working_file_df.to_excel(writer, sheet_name='Source - Working File', index=False)

                st.download_button(
                    label="Download Full Reconciliation Report (Excel)",
                    data=output.getvalue(),
                    file_name="Audit_Reconciliation_Report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

                logging.info("Reconciliation completed successfully.")

            except Exception as e:
                st.error(f"An error occurred: {e}")
                logging.error(f"Error during reconciliation: {e}", exc_info=True)

        else:
            st.error("Please upload all three required files to proceed.")

if __name__ == "__main__":
    main()
