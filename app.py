import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Advanced Vendor Analytics", layout="wide")

# --- CONFIG & CONSTANTS ---
TARGET_VENDORS = ["Candor Foods Pvt Ltd.", "Evergreen Foods and Snacks Pvt Ltd"]
DB_FILE = "vendor_analytics_db.xlsx"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            return pd.read_excel(DB_FILE, sheet_name="POs"), pd.read_excel(DB_FILE, sheet_name="Bills")
        except:
            return pd.DataFrame(), pd.DataFrame()
    return pd.DataFrame(), pd.DataFrame()

po_db, bill_db = load_data()

# --- SIDEBAR: DATA MANAGEMENT ---
st.sidebar.header("📂 Data Management")
po_file = st.sidebar.file_uploader("Upload Purchase Order CSV", type="csv")
bill_files = st.sidebar.file_uploader("Upload Bill CSVs", type="csv", accept_multiple_files=True)

if st.sidebar.button("Process & Save Data"):
    if po_file:
        df_po = pd.read_csv(po_file)
        df_po = df_po[df_po['Vendor Name'].str.strip().isin(TARGET_VENDORS)]
        df_po['Purchase Order Date'] = pd.to_datetime(df_po['Purchase Order Date'], dayfirst=True)
        df_po['Purchase Order Number'] = df_po['Purchase Order Number'].astype(str).str.strip()
        df_po['Item Total'] = pd.to_numeric(df_po['Item Total'], errors='coerce').fillna(0)
        po_db = df_po.drop_duplicates()

    bill_list = []
    if bill_files:
        for f in bill_files:
            temp_df = pd.read_csv(f)
            # Standardize based on user file structures
            if 'Reference Number' in temp_df.columns: 
                temp_df = temp_df.rename(columns={'Reference Number': 'PO_Ref', 'Date': 'Bill_Date'})
            elif 'Reference Invoice Type' in temp_df.columns: 
                temp_df = temp_df.rename(columns={'Reference Invoice Type': 'PO_Ref', 'Bill Date': 'Bill_Date'})
            
            temp_df = temp_df[temp_df['Vendor Name'].str.strip().isin(TARGET_VENDORS)]
            temp_df['Bill_Date'] = pd.to_datetime(temp_df['Bill_Date'], dayfirst=True, errors='coerce')
            temp_df['PO_Ref'] = temp_df['PO_Ref'].astype(str).str.strip()
            bill_list.append(temp_df)
        
        if bill_list:
            bill_db = pd.concat(bill_list).drop_duplicates()

    with pd.ExcelWriter(DB_FILE) as writer:
        po_db.to_excel(writer, sheet_name="POs", index=False)
        bill_db.to_excel(writer, sheet_name="Bills", index=False)
    st.sidebar.success("Database Updated!")
    st.rerun()

# --- ANALYTICS ENGINE ---
st.title("📊 Supplier Performance & Spend Dashboard")

if po_db.empty or bill_db.empty:
    st.info("Please upload your PO and Bill files to begin.")
else:
    # 1. CORE DATA MERGE
    merged = pd.merge(bill_db, po_db, left_on='PO_Ref', right_on='Purchase Order Number', how='inner')
    merged['Lead_Time'] = (merged['Bill_Date'] - merged['Purchase Order Date']).dt.days
    merged = merged[merged['Lead_Time'] >= 0] 

    # Identify the correct item and vendor columns (suffixes from merge)
    item_col = 'Item Name_y' if 'Item Name_y' in merged.columns else 'Item Name'
    vendor_col = 'Vendor Name_y' if 'Vendor Name_y' in merged.columns else 'Vendor Name'

    # 2. SIDEBAR FILTERS
    st.sidebar.divider()
    st.sidebar.header("🔍 Filter Selection")
    
    # Vendor
    v_list = sorted(merged[vendor_col].unique().tolist())
    vendor_choice = st.sidebar.selectbox("Vendor Name", ["All Vendors"] + v_list)
    f_df = merged.copy()
    if vendor_choice != "All Vendors":
        f_df = f_df[f_df[vendor_col] == vendor_choice]

    # Time Filter
    min_d = f_df['Purchase Order Date'].min().date()
    max_d = f_df['Purchase Order Date'].max().date()
    dr = st.sidebar.date_input("PO Date Range", [min_d, max_d])
    if len(dr) == 2:
        f_df = f_df[(f_df['Purchase Order Date'].dt.date >= dr[0]) & 
                    (f_df['Purchase Order Date'].dt.date <= dr[1])]

    # PO Number
    po_list = ["All POs"] + sorted(f_df['Purchase Order Number'].unique().tolist())
    selected_po = st.sidebar.selectbox("PO Number", po_list)
    if selected_po != "All POs":
        f_df = f_df[f_df['Purchase Order Number'] == selected_po]

    # Item Name
    it_list = ["All Items"] + sorted(f_df[item_col].unique().tolist())
    selected_item = st.sidebar.selectbox("Item Name", it_list)
    if selected_item != "All Items":
        f_df = f_df[f_df[item_col] == selected_item]

    # 3. KPI METRICS (Top of Page)
    # Using drop_duplicates on the filtered df to avoid over-counting values per PO
    unique_pos = f_df.drop_duplicates(subset=['Purchase Order Number', item_col])
    
    m1, m2, m3 = st.columns(3)
    total_val = unique_pos['Item Total'].sum()
    num_pos = unique_pos['Purchase Order Number'].nunique()
    avg_lt = f_df['Lead_Time'].mean()

    m1.metric("Total Order Value", f"₹{total_val:,.2f}")
    m2.metric("Total POs Count", f"{num_pos}")
    m3.metric("Avg Lead Time", f"{avg_lt:.1f} Days")

    # 4. VISUALIZATIONS
    c1, c2 = st.columns(2)
    with c1:
        po_chart = f_df.groupby('Purchase Order Number')['Lead_Time'].mean().reset_index()
        st.plotly_chart(px.bar(po_chart, x='Purchase Order Number', y='Lead_Time', 
                              title="Lead Time per PO (Days)", color_discrete_sequence=['#00CC96']), use_container_width=True)
    with c2:
        item_chart = f_df.groupby(item_col)['Lead_Time'].mean().reset_index()
        st.plotly_chart(px.bar(item_chart, y=item_col, x='Lead_Time', orientation='h', 
                              title="Efficiency by Item", color='Lead_Time', color_continuous_scale='Bluered'), use_container_width=True)

    # 5. DETAILED TABLE
    st.subheader("📋 fulfillment Tracking Table")
    # Display columns matching your request
    display_cols = [
        'Purchase Order Number', 'Purchase Order Date', vendor_col, 
        item_col, 'QuantityOrdered', 'Item Total', 'Bill_Date', 'Lead_Time'
    ]
    st.dataframe(f_df[display_cols].rename(columns={vendor_col: 'Vendor', item_col: 'Item Name'}), use_container_width=True)

if st.sidebar.button("🗑️ Reset Database"):
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    st.rerun()
