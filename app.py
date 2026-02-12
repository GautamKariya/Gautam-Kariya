import streamlit as st
import pandas as pd
from datetime import date
import logging
import io

# Imports - streamlit handles imports from the same directory usually
try:
    from parser import parse_portfolio_html
    from corporate_actions import process_corporate_actions
    from dividend_engine import calculate_dividends
except ImportError:
    # Fallback if running from a different context
    import sys
    import os
    sys.path.append(os.getcwd())
    from parser import parse_portfolio_html
    from corporate_actions import process_corporate_actions
    from dividend_engine import calculate_dividends

# Set up basic configuration
st.set_page_config(page_title="Quarterly Investment & Corporate Action Audit Tool", layout="wide")

# Setup logging
logging.basicConfig(filename='audit_log.txt', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    st.title("Quarterly Investment & Corporate Action Audit Tool")

    st.sidebar.header("Input Parameters")

    # Date selection for the quarter
    col1, col2 = st.sidebar.columns(2)
    with col1:
        # Default to previous quarter logic or just current year
        today = date.today()
        default_start = date(today.year, 1, 1)
        start_date = st.sidebar.date_input("Quarter Start Date", default_start)
    with col2:
        default_end = date(today.year, 3, 31)
        end_date = st.sidebar.date_input("Quarter End Date", default_end)

    # File uploads
    portfolio_file = st.sidebar.file_uploader("Upload Portfolio HTML", type=["html", "htm"])
    corporate_file = st.sidebar.file_uploader("Upload Corporate Action CSV", type=["csv"])

    if st.sidebar.button("Run Reconciliation"):
        if portfolio_file and corporate_file:
            st.info("Processing files...")

            try:
                # 1. Parse Portfolio
                # Streamlit file uploader returns a BytesIO object.
                # Specifically for HTML parsing with BeautifulSoup, we need the string content.
                portfolio_bytes = portfolio_file.read()
                # Try decoding with utf-8, fallback to latin-1 if needed
                try:
                    portfolio_content = portfolio_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    portfolio_content = portfolio_bytes.decode('latin-1')

                portfolio_df = parse_portfolio_html(portfolio_content)

                st.success(f"Parsed Portfolio: {len(portfolio_df)} ISINs found.")

                # 2. Process Corporate Actions
                # process_corporate_actions expects a file-like object or path.
                # Streamlit file object works with pd.read_csv directly.
                # We need to reset the pointer just in case, though streamlit usually gives a fresh one.
                corporate_file.seek(0)

                # However, our process_corporate_actions takes 'file'.
                # pd.read_csv accepts the file-like object.
                corporate_df = process_corporate_actions(corporate_file, start_date, end_date)

                st.success(f"Processed Corporate Actions: {len(corporate_df)} Dividends found in selected quarter.")

                # 3. Calculate Dividends
                dividend_df, exception_df = calculate_dividends(portfolio_df, corporate_df)

                # Display Results
                st.subheader("Reconciliation Results")

                # Create tabs
                tab1, tab2, tab3 = st.tabs(["Dividend Working", "Exception Report", "Portfolio Summary"])

                with tab1:
                    st.write("### Dividend Working")
                    if not dividend_df.empty:
                        st.dataframe(dividend_df)
                        total_div = dividend_df['Expected Dividend'].sum()
                        st.metric("Total Expected Dividend", f"{total_div:,.2f}")
                    else:
                        st.write("No dividends expected for this quarter.")

                with tab2:
                    st.write("### Exception Report")
                    if not exception_df.empty:
                        st.dataframe(exception_df)
                    else:
                        st.write("No exceptions found.")

                with tab3:
                    st.write("### Portfolio Summary")
                    st.dataframe(portfolio_df)

                # 4. Generate Excel Report
                output = io.BytesIO()
                # Use xlsxwriter or openpyxl. We installed openpyxl.
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    if not portfolio_df.empty:
                        portfolio_df.to_excel(writer, sheet_name='Portfolio Holding', index=False)
                    if not dividend_df.empty:
                        dividend_df.to_excel(writer, sheet_name='Dividend Working', index=False)
                    if not exception_df.empty:
                        exception_df.to_excel(writer, sheet_name='Exception Report', index=False)

                # Seek to beginning
                # output.seek(0) # Not needed for getvalue()

                st.download_button(
                    label="Download Excel Working Paper",
                    data=output.getvalue(),
                    file_name="Dividend_Reconciliation_Report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

                logging.info("Reconciliation completed successfully.")

            except Exception as e:
                st.error(f"An error occurred: {e}")
                logging.error(f"Error during reconciliation: {e}", exc_info=True)
                # st.exception(e) # Optional: show full stack trace in UI

        else:
            st.error("Please upload both files to proceed.")

if __name__ == "__main__":
    main()
