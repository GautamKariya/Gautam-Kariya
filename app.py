import streamlit as st
import pandas as pd
from datetime import date
import logging
import io

# Setup logging
logging.basicConfig(filename='audit_log.txt', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Imports
try:
    from parser import parse_portfolio_html_v2
    from corporate_actions import process_corporate_actions
    from working_parser import parse_client_working_v2
    from dividend_engine import verify_audit
except ImportError:
    import sys
    import os
    sys.path.append(os.getcwd())
    from parser import parse_portfolio_html_v2
    from corporate_actions import process_corporate_actions
    from working_parser import parse_client_working_v2
    from dividend_engine import verify_audit

st.set_page_config(page_title="RPL Investment Report – Shares Audit Verification Tool", layout="wide")

def main():
    st.title("RPL Investment Report – Shares Audit Verification Tool")

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
    portfolio_file = st.sidebar.file_uploader("1. Upload Portfolio Statement (HTML)", type=["html", "htm"])
    corporate_file = st.sidebar.file_uploader("2. Upload Corporate Action CSV", type=["csv"])
    client_curr_file = st.sidebar.file_uploader("3. Upload Current Quarter Client Working (Excel)", type=["xlsx", "xls"])
    client_prev_file = st.sidebar.file_uploader("4. Upload Previous Quarter Client Working (Optional)", type=["xlsx", "xls"])

    if st.sidebar.button("Run Verification"):
        if portfolio_file and corporate_file and client_curr_file:
            st.info("Processing files...")

            try:
                # 1. Parse Portfolio HTML
                portfolio_bytes = portfolio_file.read()
                try:
                    portfolio_content = portfolio_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    portfolio_content = portfolio_bytes.decode('latin-1')

                portfolio_df = parse_portfolio_html_v2(portfolio_content)
                if portfolio_df.empty:
                    st.warning("Parsed Portfolio HTML but found 0 ISINs. Check structure.")
                else:
                    st.success(f"Parsed Portfolio HTML: {len(portfolio_df)} ISINs found.")

                # 2. Parse Client Working Files
                try:
                    client_df = parse_client_working_v2(client_curr_file, client_prev_file)
                except ValueError as ve:
                    # Specific parser error
                    st.error(f"Error Parsing Client Working File: {str(ve)}")
                    return
                except Exception as e:
                    st.error(f"Unexpected Error Parsing Client Working File: {str(e)}")
                    return

                if client_df.empty:
                    st.error("Parsed Client Working File but found 0 rows. Check 'Shares' sheet content.")
                    return

                st.success(f"Parsed Client Working: {len(client_df)} rows found.")
                if client_prev_file:
                    st.info("Previous Quarter file used for dividend isolation.")
                else:
                    st.warning("Previous Quarter file NOT provided. Assuming Current Cumulative = Quarterly Dividend.")

                # 3. Process Corporate Actions
                corporate_file.seek(0)
                corporate_df = process_corporate_actions(corporate_file, start_date, end_date)
                st.success(f"Processed Corporate Actions: {len(corporate_df)} Dividends/Bonuses found in selected quarter.")

                # 4. Run Audit Verification Logic
                reconciliation_df, dividend_df, bonus_df, exception_df = verify_audit(portfolio_df, client_df, corporate_df)

                # Display Results
                st.subheader("Audit Dashboard")

                tab1, tab2, tab3, tab4, tab5 = st.tabs([
                    "Closing Units Reconciliation",
                    "Dividend Verification",
                    "Bonus Verification",
                    "Exception Summary",
                    "Source Data"
                ])

                with tab1:
                    st.write("### Closing Units (Client vs Portfolio)")
                    if not reconciliation_df.empty:
                        def highlight_status(row):
                            return ['background-color: #ffcccc' if row['Status'] != 'Matched' else ''] * len(row)
                        st.dataframe(reconciliation_df.style.apply(highlight_status, axis=1))
                    else:
                        st.info("No data.")

                with tab2:
                    st.write("### Dividend Verification")
                    st.write("Comparison: Expected (DPS * Port Units) vs Client Quarterly Increase")
                    if not dividend_df.empty:
                        st.dataframe(dividend_df)
                        total_expected = dividend_df['Expected Dividend'].sum()
                        total_client = dividend_df['Client Increase'].sum()
                        st.metric("Total Expected", f"{total_expected:,.2f}", delta=f"{total_client - total_expected:,.2f}")
                    else:
                        st.info("No dividends matched.")

                with tab3:
                    st.write("### Bonus Verification")
                    if not bonus_df.empty:
                        st.dataframe(bonus_df)
                    else:
                        st.info("No bonus entries found.")

                with tab4:
                    st.write("### Exception Summary")
                    if not exception_df.empty:
                        st.error(f"Found {len(exception_df)} exceptions.")
                        st.dataframe(exception_df)
                    else:
                        st.success("No exceptions found!")

                with tab5:
                     col_a, col_b = st.columns(2)
                     with col_a:
                         st.write("#### Parsed Portfolio")
                         st.dataframe(portfolio_df)
                     with col_b:
                         st.write("#### Parsed Client Working")
                         st.dataframe(client_df)

                # 5. Generate Excel Report
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    if not reconciliation_df.empty:
                        reconciliation_df.to_excel(writer, sheet_name='Closing Units Reconciliation', index=False)
                    if not dividend_df.empty:
                        dividend_df.to_excel(writer, sheet_name='Dividend Verification', index=False)
                    if not bonus_df.empty:
                        bonus_df.to_excel(writer, sheet_name='Bonus Verification', index=False)
                    if not exception_df.empty:
                        exception_df.to_excel(writer, sheet_name='Exception Summary', index=False)

                    # Dump source data for reference
                    if not portfolio_df.empty:
                        portfolio_df.to_excel(writer, sheet_name='Source - Portfolio', index=False)
                    if not client_df.empty:
                        client_df.to_excel(writer, sheet_name='Source - Client', index=False)

                st.download_button(
                    label="Download Audit Report (Excel)",
                    data=output.getvalue(),
                    file_name="Audit_Verification_Report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

                logging.info("Verification completed successfully.")

            except Exception as e:
                st.error(f"An error occurred: {e}")
                logging.error(f"Error during verification: {e}", exc_info=True)

        else:
            st.error("Please upload the 3 required files (Portfolio, Corp Action, Current Client Working) to proceed.")

if __name__ == "__main__":
    main()
