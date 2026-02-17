import streamlit as st
import pandas as pd
from datetime import date
import logging
import io

# Setup logging
logging.basicConfig(filename='audit_log.txt', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Imports
try:
    from portfolio_parser import parse_portfolio_html_equity
    from corporate_action_parser import parse_corporate_actions_equity
    from working_parser import parse_shares_input_file
    from bhav_copy_parser import parse_bhav_copy
    from shares_engine import verify_shares_audit
except ImportError:
    import sys
    import os
    sys.path.append(os.getcwd())
    from portfolio_parser import parse_portfolio_html_equity
    from corporate_action_parser import parse_corporate_actions_equity
    from working_parser import parse_shares_input_file
    from bhav_copy_parser import parse_bhav_copy
    from shares_engine import verify_shares_audit

st.set_page_config(page_title="RPL Shares Audit Verification Engine", layout="wide")

def main():
    st.title("RPL Shares Audit Verification Engine")
    st.markdown("**Strict Equity-Only Audit Tool**")

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
    portfolio_file = st.sidebar.file_uploader("1. Portfolio Statement (HTML)", type=["html", "htm"])
    corporate_file = st.sidebar.file_uploader("2. Corporate Action (CSV)", type=["csv"])
    shares_file = st.sidebar.file_uploader("3. Shares Input File (Excel)", type=["xlsx", "xls"])
    bhav_file = st.sidebar.file_uploader("4. NSE Bhav Copy (CSV)", type=["csv"])

    if st.sidebar.button("Run Shares Verification"):
        if portfolio_file and corporate_file and shares_file and bhav_file:
            st.info("Processing files...")

            try:
                # 1. Parse Portfolio HTML
                portfolio_bytes = portfolio_file.read()
                try:
                    portfolio_content = portfolio_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    portfolio_content = portfolio_bytes.decode('latin-1')

                portfolio_df = parse_portfolio_html_equity(portfolio_content)
                if portfolio_df.empty:
                    st.warning("Parsed Portfolio HTML but found 0 Equity ISINs (INE...). Check file.")
                else:
                    st.success(f"Parsed Portfolio: {len(portfolio_df)} Equity ISINs found.")

                # 2. Parse Shares Input File
                try:
                    shares_df = parse_shares_input_file(shares_file)
                except ValueError as ve:
                    st.error(f"Error Parsing Shares Input: {str(ve)}")
                    return
                except Exception as e:
                    st.error(f"Unexpected Error Parsing Shares Input: {str(e)}")
                    return

                if shares_df.empty:
                    st.error("Parsed Shares Input but found 0 rows.")
                    return
                st.success(f"Parsed Shares Input: {len(shares_df)} rows found.")

                # 3. Parse Corporate Actions
                corporate_file.seek(0)
                corporate_df = parse_corporate_actions_equity(corporate_file, start_date, end_date)
                st.success(f"Processed Corporate Actions: {len(corporate_df)} relevant entries.")

                # 4. Parse Bhav Copy
                bhav_file.seek(0)
                bhav_df = parse_bhav_copy(bhav_file)
                if bhav_df.empty:
                    st.error("Parsed Bhav Copy but found 0 rows or missing columns (ISIN, CLOSE).")
                else:
                    st.success(f"Parsed Bhav Copy: {len(bhav_df)} ISINs found.")

                # 5. Run Verification Engine
                summary_df, exceptions_df, working_papers = verify_shares_audit(portfolio_df, shares_df, corporate_df, bhav_df)

                # Display Results
                st.subheader("Audit Dashboard")

                tab1, tab2, tab3 = st.tabs(["Reconciliation Summary", "Exception Report", "Source Data"])

                with tab1:
                    st.write("### Reconciliation Summary")
                    if not summary_df.empty:
                         # Highlight rows with exceptions
                        def highlight_status(row):
                            return ['background-color: #ffcccc' if row['Status'] != 'OK' else 'background-color: #ccffcc'] * len(row)
                        st.dataframe(summary_df.style.apply(highlight_status, axis=1))
                    else:
                        st.info("No data.")

                with tab2:
                    st.write("### Exception Report")
                    if not exceptions_df.empty:
                        st.error(f"Found {len(exceptions_df)} mismatches.")
                        st.dataframe(exceptions_df)
                    else:
                        st.success("No exceptions found! All checks matched.")

                with tab3:
                    st.write("#### Parsed Portfolio")
                    st.dataframe(portfolio_df)
                    st.write("#### Parsed Shares Input")
                    st.dataframe(shares_df)

                # 6. Generate Excel Report
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    # Summary & Exceptions
                    if not summary_df.empty:
                        summary_df.to_excel(writer, sheet_name='Reconciliation Summary', index=False)
                    if not exceptions_df.empty:
                        exceptions_df.to_excel(writer, sheet_name='Detailed Exception Report', index=False)

                    # Working Papers
                    if not working_papers['Closing Units'].empty:
                        working_papers['Closing Units'].to_excel(writer, sheet_name='Closing Units Verification', index=False)
                    if not working_papers['Bonus'].empty:
                        working_papers['Bonus'].to_excel(writer, sheet_name='Bonus Verification', index=False)
                    if not working_papers['Dividend'].empty:
                        working_papers['Dividend'].to_excel(writer, sheet_name='Dividend Verification', index=False)
                    if not working_papers['Market Price'].empty:
                        working_papers['Market Price'].to_excel(writer, sheet_name='Market Price Verification', index=False)
                    if not working_papers['MV & UGL'].empty:
                        working_papers['MV & UGL'].to_excel(writer, sheet_name='Market Value & UGL', index=False)

                    # Source Dump
                    shares_df.to_excel(writer, sheet_name='Source - Shares Input', index=False)

                st.download_button(
                    label="Download Audit Working Paper (Excel)",
                    data=output.getvalue(),
                    file_name="Shares_Audit_Working_Paper.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

                logging.info("Verification completed successfully.")

            except Exception as e:
                st.error(f"An error occurred: {e}")
                logging.error(f"Error during verification: {e}", exc_info=True)

        else:
            st.error("Please upload all 4 required files to proceed.")

if __name__ == "__main__":
    main()
