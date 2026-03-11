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
        return pd.read_excel(DB_FILE, sheet_name="POs"), pd.read_excel(DB_FILE, sheet_name="Bills")
    return pd.DataFrame(), pd.DataFrame()

po_db, bill_db = load_data()

# --- SIDEBAR: DATA UPLOAD & PERSISTENCE ---
st.sidebar.header("📂 Data Management")
po_file = st.sidebar.file_uploader("Upload Purchase Order CSV", type="csv")
bill_files = st.sidebar.file_uploader("Upload Bill CSVs", type="csv", accept_multiple_files=True)

if st.sidebar.button("Process & Save Data"):
    if po_file:
        df_po = pd.read_csv(po_file)
        df_po = df_po[df_po['Vendor Name'].isin(TARGET_VENDORS)]
        df_po['Purchase Order Date'] = pd.to_datetime(df_po['Purchase Order Date'], dayfirst=True)
        df_po['Purchase Order Number'] = df_po['Purchase Order Number'].astype(str).str.strip()
        # Clean currency/numeric if needed
        if 'Item Total' in df_po.columns:
            df_po['Item Total'] = pd.to_numeric(df_po['Item Total'], errors='coerce').fillna(0)
        po_db = df_po.drop_duplicates()

    bill_list = []
    if bill_files:
        for f in bill_files:
            temp_df = pd.read_csv(f)
            # Standardize based on file structures
            if 'Reference Number' in temp_df.columns: 
                temp_df = temp_df.rename(columns={'Reference Number': 'PO_Ref', 'Date': 'Bill_Date'})
            elif 'Reference Invoice Type' in temp_df.columns: 
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
    st.sidebar.success("Database Updated!")
    st.rerun()

# --- ANALYTICS ENGINE ---
st.title("📦 Procurement Lead Time & Spend Tracker")

if po_db.empty or bill_db.empty:
    st.info("Please upload files to see the analysis.")
else:
    # 1. INITIAL MERGE
    merged = pd.merge(bill_db, po_db, left_on='PO_Ref', right_on='Purchase Order Number', how='inner')
    merged['Lead_Time'] = (merged['Bill_Date'] - merged['Purchase Order Date']).dt.days
    merged = merged[merged['Lead_Time'] >= 0] # Remove date anomalies

    # 2. SIDEBAR FILTERS
    st.sidebar.divider()
    st.sidebar.header("🔍 Filter Options")
    
    # Vendor Filter
    vendor_choice = st.sidebar.selectbox("Vendor Name", ["All"] + TARGET_VENDORS)
    f_df = merged.copy()
    if vendor_choice != "All":
        f_df = f_df[f_df['Vendor Name_y'] == vendor_choice]

    # Time Filter (PO Date)
    min_date = f_df['Purchase Order Date'].min().date()
    max_date = f_df['Purchase Order Date'].max().date()
    date_range = st.sidebar.date_input("PO Date Range", [min_date, max_date])
    if len(date_range) == 2:
        f_df = f_df[(f_df['Purchase Order Date'].dt.date >= date_range[0]) & 
                    (f_df['Purchase Order Date'].dt.date <= date_range[1])]

    # PO Number Filter
    po_list = ["All"] + sorted(f_df['Purchase Order Number'].unique().tolist())
    selected_po = st.sidebar.selectbox("PO Number", po_list)
    if selected_po != "All":
        f_df = f_df[f_df['Purchase Order Number'] == selected_po]

    # Item Filter
    item_list = ["All"] + sorted(f_df['Item Name'].unique().tolist())
    selected_item = st.sidebar.selectbox("Item Name", item_list)
    if selected_item != "All":
        f_df = f_df[f_df['Item Name'] == selected_item]

    # 3. TOP LEVEL METRICS
    m1, m2, m3 = st.columns(3)
    total_val = f_df['Item Total'].sum()
    num_pos = f_df['Purchase Order Number'].nunique()
    avg_lt = f_df['Lead_Time'].mean()

    m1.metric("Total PO Value", f"₹{total_val:,.2f}")
    m2.metric("Total POs", f"{num_pos}")
    m3.metric("Avg Lead Time", f"{avg_lt:.1f} Days")

    # 4. CHARTS
    c1, c2 = st.columns(2)
    with c1:
        po_chart_data = f_df.groupby('Purchase Order Number')['Lead_Time'].mean().reset_index()
        st.plotly_chart(px.bar(po_chart_data, x='Purchase Order Number', y='Lead_Time', title="Lead Time per PO"), use_container_width=True)
    with c2:
        item_chart_data = f_df.groupby('Item Name')['Lead_Time'].mean().reset_index()
        st.plotly_chart(px.bar(item_chart_data, y='Item Name', x='Lead_Time', orientation='h', title="Avg Lead Time by Item"), use_container_width=True)

    # 5. DETAILED TABLE
    st.subheader("Detailed Transaction View")
    # Selection of requested columns
    display_cols = [
        'Purchase Order Number', 
        'Purchase Order Date', 
        'Vendor Name_y', 
        'Item Name', 
        'QuantityOrdered', 
        'Item Total', 
        'Bill_Date', 
        'Lead_Time'
    ]
    st.dataframe(f_df[display_cols].rename(columns={'Vendor Name_y': 'Vendor Name'}), use_container_width=True)

if st.sidebar.button("🗑️ Reset Database"):
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    st.rerun()
