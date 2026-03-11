import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Vendor Lead Time Tracker", layout="wide")

# --- SETTINGS & VENDORS ---
TARGET_VENDORS = ["Candor Foods Pvt Ltd.", "Evergreen Foods and Snacks Pvt Ltd"]
DB_FILE = "vendor_analytics_db.xlsx"

def clean_currency(column):
    """Removes currency symbols and commas to convert to float."""
    return column.replace(r'[₹,]', '', regex=True).astype(float)

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
    # Process POs
    if po_file:
        df_po = pd.read_csv(po_file)
        df_po = df_po[df_po['Vendor Name'].isin(TARGET_VENDORS)]
        df_po['Purchase Order Date'] = pd.to_datetime(df_po['Purchase Order Date'], dayfirst=True)
        po_db = df_po.drop_duplicates(subset=['Purchase Order Number', 'Item Name'])

    # Process Bills
    bill_list = []
    if bill_files:
        for f in bill_files:
            temp_df = pd.read_csv(f)
            # Standardize column names based on your uploaded files
            if 'Reference Number' in temp_df.columns: # Bills (1)
                temp_df = temp_df.rename(columns={'Reference Number': 'PO_Ref', 'Date': 'Bill_Date'})
            elif 'Bill Number' in temp_df.columns: # Bill (2)
                temp_df = temp_df.rename(columns={'Bill Number': 'Bill_No', 'Bill Date': 'Bill_Date', 'Reference Invoice Type': 'PO_Ref'})
            
            temp_df = temp_df[temp_df['Vendor Name'].isin(TARGET_VENDORS)]
            temp_df['Bill_Date'] = pd.to_datetime(temp_df['Bill_Date'], dayfirst=True, errors='coerce')
            bill_list.append(temp_df)
        
        if bill_list:
            bill_db = pd.concat(bill_list).drop_duplicates()

    with pd.ExcelWriter(DB_FILE) as writer:
        po_db.to_excel(writer, sheet_name="POs", index=False)
        bill_db.to_excel(writer, sheet_name="Bills", index=False)
    st.sidebar.success("Analysis Ready!")
    st.rerun()

# --- OUTPUT / ANALYTICS ---
st.title("📊 Vendor Performance Analytics")

if po_db.empty or bill_db.empty:
    st.info("Upload files and click 'Process Data' to view analytics for Candor and Evergreen.")
else:
    # Merge Logic
    # We join on PO Number. Note: In your Bills, this is 'PO_Ref'
    merged = pd.merge(
        bill_db, 
        po_db, 
        left_on='PO_Ref', 
        right_on='Purchase Order Number', 
        how='inner'
    )
    
    # Calculate Lead Time
    merged['Lead_Time'] = (merged['Bill_Date'] - merged['Purchase Order Date']).dt.days
    # Filter out any negative lead times (date errors)
    merged = merged[merged['Lead_Time'] >= 0]

    # 1. Vendor Dropdown
    selected_vendor = st.selectbox("Select Vendor", TARGET_VENDORS)
    v_data = merged[merged['Vendor Name_x'] == selected_vendor]

    # 2. Layout
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Avg Lead Time per PO")
        po_metrics = v_data.groupby('Purchase Order Number')['Lead_Time'].mean().reset_index()
        fig_po = px.bar(po_metrics, x='Purchase Order Number', y='Lead_Time', 
                        color='Lead_Time', title=f"Fulfillment Speed: {selected_vendor}")
        st.plotly_chart(fig_po, use_container_width=True)

    with col2:
        st.subheader("Avg Lead Time by Item")
        item_metrics = v_data.groupby('Item Name')['Lead_Time'].mean().reset_index()
        fig_item = px.bar(item_metrics, x='Lead_Time', y='Item Name', orientation='h',
                         title="Item-wise Delivery Delay", color_continuous_scale='Reds')
        st.plotly_chart(fig_item, use_container_width=True)

    # 3. Management View
    with st.expander("View / Delete Specific Entries"):
        st.write("Full Transaction Record:")
        st.dataframe(v_data[['Purchase Order Number', 'Bill_Date', 'Item Name', 'Lead_Time']])
        
        if st.button("Delete Entire Database"):
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
                st.rerun()
