import streamlit as st
import pandas as pd
from datetime import date
import shares_input_parser
import portfolio_parser
import corporate_action_parser
import bhav_copy_parser
import shares_engine

st.set_page_config(page_title="Shares Audit Tool", layout="wide")

st.title("Shares Audit Verification Tool")

st.markdown("### 1. Configuration")
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date", value=date(date.today().year, 1, 1))
with col2:
    end_date = st.date_input("End Date", value=date.today())

st.markdown("### 2. Upload Files")

col_up1, col_up2 = st.columns(2)
with col_up1:
    portfolio_file = st.file_uploader("Upload Portfolio Statement (HTML)", type=['html', 'htm'])
    shares_file = st.file_uploader("Upload Shares Input File (Excel)", type=['xlsx', 'xls'])

with col_up2:
    corp_action_file = st.file_uploader("Upload Corporate Action File (CSV)", type=['csv'])
    bhav_copy_file = st.file_uploader("Upload NSE Bhav Copy (CSV)", type=['csv'])

st.markdown("### 3. Manual Input (REIT/Other)")
st.caption("Optional: Add manual Dividend Rate or Repayment Rate for securities not in Corporate Action (e.g. REITs).")

# Manual Input Table
if 'manual_data' not in st.session_state:
    st.session_state.manual_data = pd.DataFrame(columns=['ISIN', 'Dividend Rate', 'Repayment Rate'])

# Editable Data Editor
manual_df = st.data_editor(
    st.session_state.manual_data,
    num_rows="dynamic",
    column_config={
        "ISIN": st.column_config.TextColumn("ISIN", help="Enter ISIN (e.g. INE...)"),
        "Dividend Rate": st.column_config.NumberColumn("Dividend Rate", help="DPS", format="%.4f"),
        "Repayment Rate": st.column_config.NumberColumn("Repayment Rate", help="Repayment per Unit", format="%.4f"),
    },
    key="manual_input_editor"
)

if st.button("Run Shares Verification", type="primary"):
    if not (portfolio_file and shares_file and corp_action_file and bhav_copy_file):
        st.error("Please upload all 4 required files.")
    else:
        with st.spinner("Parsing files..."):
            # Reset pointers
            portfolio_file.seek(0)
            shares_file.seek(0)
            corp_action_file.seek(0)
            bhav_copy_file.seek(0)

            # Parse Shares Input
            shares_df, shares_err = shares_input_parser.parse_shares_input(shares_file)
            if shares_err:
                st.error(f"Shares Input Error: {shares_err}")
                st.stop()

            # Parse Portfolio
            portfolio_df, port_err = portfolio_parser.parse_portfolio_html(portfolio_file)
            if port_err:
                st.error(f"Portfolio Error: {port_err}")
                st.stop()

            # Parse Corporate Action
            corp_df, corp_err = corporate_action_parser.parse_corporate_action(corp_action_file, start_date, end_date)
            if corp_err:
                st.error(f"Corporate Action Error: {corp_err}")
                st.stop()

            # Parse Bhav Copy
            bhav_df, bhav_err = bhav_copy_parser.parse_bhav_copy(bhav_copy_file)
            if bhav_err:
                st.error(f"Bhav Copy Error: {bhav_err}")
                st.stop()

        with st.spinner("Running verification..."):
            # Prepare Manual Data
            # manual_df comes from data_editor

            summary, output_dfs, exceptions_df = shares_engine.run_verification(
                shares_df, portfolio_df, corp_df, bhav_df, manual_df
            )

        st.success("Verification Complete!")

        # Display Summary
        st.subheader("Summary")
        st.dataframe(pd.DataFrame([summary]))

        # Display Exceptions
        if not exceptions_df.empty:
            st.subheader("Exceptions Found")
            st.dataframe(exceptions_df)
        else:
            st.info("No exceptions found.")

        # Download
        excel_data = shares_engine.generate_excel_report(output_dfs, exceptions_df)

        st.download_button(
            label="Download Working Paper (Excel)",
            data=excel_data,
            file_name="Shares_Audit_Working_Paper.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
