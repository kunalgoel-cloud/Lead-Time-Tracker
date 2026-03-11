import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Vendor Lead Time Tracker", layout="wide")

# --- SETTINGS & VENDORS ---
TARGET_VENDORS = ["Candor Foods Pvt Ltd.", "Evergreen Foods and Snacks Pvt Ltd"]
DB_FILE = "vendor_analytics_db.xlsx"

def load_data():
    if os.path.exists(DB_FILE):
        return pd.read_excel(DB_FILE, sheet_name="POs"), pd.read_excel(DB_FILE, sheet_name="Bills")
    return pd.DataFrame(), pd.DataFrame()

po_db, bill_db = load_data()

# --- SIDEBAR: UPLOADS ---
st.sidebar.header("📂 Upload Data")
po_file = st.sidebar.file_uploader("Upload Purchase Order CSV", type="csv")
bill_files = st.sidebar.file_uploader("Upload Bill CSVs", type="csv", accept_multiple_files=True)

if st.sidebar.button("Process Data"):
    if po_file:
        df_po = pd.read_csv(po_file)
        df_po = df_po[df_po['Vendor Name'].isin(TARGET_VENDORS)]
        df_po['Purchase Order Date'] = pd.to_datetime(df_po['Purchase Order Date'], dayfirst=True)
        # Clean PO Numbers for better matching
        df_po['Purchase Order Number'] = df_po['Purchase Order Number'].astype(str).str.strip()
        po_db = df_po.drop_duplicates(subset=['Purchase Order Number', 'Item Name'])

    bill_list = []
    if bill_files:
        for f in bill_files:
            temp_df = pd.read_csv(f)
            # Standardize column names based on your uploaded files
            if 'Reference Number' in temp_df.columns: # Bills (1)
                temp_df = temp_df.rename(columns={'Reference Number': 'PO_Ref', 'Date': 'Bill_Date'})
            elif 'Reference Invoice Type' in temp_df.columns: # Bill (2)
                temp_df = temp_df.rename(columns={'Reference Invoice Type': 'PO_Ref', 'Bill Date': 'Bill_Date'})
            
            temp_df = temp_df[temp_df['Vendor Name'].isin(TARGET_VENDORS)]
            temp_df['Bill_Date'] = pd.to_datetime(temp_df['Bill_Date'], errors='coerce')
            temp_df['PO_Ref'] = temp_df['PO_Ref'].astype(str).str.strip()
            bill_list.append(temp_df)
        
        if bill_list:
            bill_db = pd.concat(bill_list).drop_duplicates()

    with pd.ExcelWriter(DB_FILE) as writer:
        po_db.to_excel(writer, sheet_name="POs", index=False)
        bill_db.to_excel(writer, sheet_name="Bills", index=False)
    st.sidebar.success("Analysis Ready!")
    st.rerun()

# --- ANALYTICS ---
st.title("📊 Vendor Performance Analytics")

if po_db.empty or bill_db.empty:
    st.info("Upload your PO and Bill files to see the analysis for Candor and Evergreen.")
else:
    # Joining the data
    merged = pd.merge(
        bill_db, 
        po_db, 
        left_on='PO_Ref', 
        right_on='Purchase Order Number', 
        how='inner'
    )
    
    # After merging, 'Item Name' becomes 'Item Name_y' (from PO) or 'Item Name_x' (from Bill)
    # We use the item name from the PO record for consistency
    item_col = 'Item Name_y' if 'Item Name_y' in merged.columns else 'Item Name'
    vendor_col = 'Vendor Name_y' if 'Vendor Name_y' in merged.columns else 'Vendor Name'

    # Calculate Lead Time
    merged['Lead_Time'] = (merged['Bill_Date'] - merged['Purchase Order Date']).dt.days
    merged = merged[merged['Lead_Time'] >= 0] # Filter out data errors

    # Filter by selected vendor
    selected_vendor = st.selectbox("Select Vendor", TARGET_VENDORS)
    v_data = merged[merged[vendor_col] == selected_vendor]

    if not v_data.empty:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Avg Lead Time per PO")
            po_metrics = v_data.groupby('Purchase Order Number')['Lead_Time'].mean().reset_index()
            fig_po = px.bar(po_metrics, x='Purchase Order Number', y='Lead_Time', 
                            title="Days from PO to Bill Date")
            st.plotly_chart(fig_po, use_container_width=True)

        with col2:
            st.subheader("Avg Lead Time by Item")
            # FIXED: Using the corrected column name from the merge
            item_metrics = v_data.groupby(item_col)['Lead_Time'].mean().reset_index()
            fig_item = px.bar(item_metrics, x='Lead_Time', y=item_col, orientation='h',
                             title="Average Delay by Product", color='Lead_Time',
                             color_continuous_scale='Reds')
            st.plotly_chart(fig_item, use_container_width=True)

        st.subheader("Fulfillment Detail Table")
        st.dataframe(v_data[['Purchase Order Number', 'Bill_Date', item_col, 'Lead_Time']])
    else:
        st.warning(f"No matching PO and Bill records found for {selected_vendor}. Ensure PO numbers in Bill files match the PO file exactly.")

if st.sidebar.button("🗑️ Reset Database"):
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    st.rerun()
