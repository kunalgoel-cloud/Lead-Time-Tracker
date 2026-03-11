import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Vendor Analytics: Weighted Lead Time", layout="wide")

# --- CONFIG ---
TARGET_VENDORS = ["Candor Foods Pvt Ltd.", "Evergreen Foods and Snacks Pvt Ltd"]
DB_FILE = "vendor_analytics_db.xlsx"

def load_db():
    if os.path.exists(DB_FILE):
        try:
            return pd.read_excel(DB_FILE, sheet_name="POs"), pd.read_excel(DB_FILE, sheet_name="Bills")
        except:
            return pd.DataFrame(), pd.DataFrame()
    return pd.DataFrame(), pd.DataFrame()

po_db, bill_db = load_db()

# --- SIDEBAR: DATA UPLOAD ---
st.sidebar.header("📂 Data Management")
po_file = st.sidebar.file_uploader("Upload Purchase Order CSV", type="csv")
bill_files = st.sidebar.file_uploader("Upload Bill CSVs", type="csv", accept_multiple_files=True)

if st.sidebar.button("Process & Update Data"):
    # 1. PROCESS POs
    if po_file:
        df_po = pd.read_csv(po_file)
        df_po['Vendor Name'] = df_po['Vendor Name'].str.strip()
        df_po = df_po[df_po['Vendor Name'].isin(TARGET_VENDORS)]
        df_po['Purchase Order Date'] = pd.to_datetime(df_po['Purchase Order Date'], dayfirst=True, errors='coerce')
        df_po['Purchase Order Number'] = df_po['Purchase Order Number'].astype(str).str.strip()
        df_po['QuantityOrdered'] = pd.to_numeric(df_po['QuantityOrdered'], errors='coerce').fillna(0)
        df_po['Item Total'] = pd.to_numeric(df_po['Item Total'], errors='coerce').fillna(0)
        po_db = df_po.drop_duplicates()

    # 2. PROCESS BILLS
    all_bills = []
    if bill_files:
        for f in bill_files:
            temp = pd.read_csv(f)
            
            # Standardize column mapping based on file patterns
            ref_col = 'Reference Number' if 'Reference Number' in temp.columns else 'Reference Invoice Type'
            date_col = 'Date' if 'Date' in temp.columns else 'Bill Date'
            item_col = 'Item Name' if 'Item Name' in temp.columns else None
            qty_col = 'Quantity' if 'Quantity' in temp.columns else None
            
            # Normalize row data
            temp['PO_Ref'] = temp[ref_col].astype(str).str.strip() if ref_col in temp.columns else None
            temp['Bill_Date'] = pd.to_datetime(temp[date_col], dayfirst=True, errors='coerce')
            temp['Vendor Name'] = temp['Vendor Name'].str.strip()
            temp['Item_Name_Bill'] = temp[item_col] if item_col else None
            
            # Capture quantity from Bill (2) specifically
            if qty_col:
                temp['Inv_Qty'] = pd.to_numeric(temp[qty_col], errors='coerce')
            else:
                temp['Inv_Qty'] = None # Will be inferred from PO for Bills (1)
            
            temp = temp[temp['Vendor Name'].isin(TARGET_VENDORS)]
            all_bills.append(temp[['PO_Ref', 'Bill_Date', 'Vendor Name', 'Item_Name_Bill', 'Inv_Qty']])
        
        if all_bills:
            bill_db = pd.concat(all_bills).drop_duplicates()

    with pd.ExcelWriter(DB_FILE) as writer:
        po_db.to_excel(writer, sheet_name="POs", index=False)
        bill_db.to_excel(writer, sheet_name="Bills", index=False)
    st.sidebar.success("Database Rebuilt!")
    st.rerun()

# --- ANALYTICS ENGINE ---
st.title("📊 Vendor Efficiency: Weighted Lead Time Tracker")

if po_db.empty or bill_db.empty:
    st.info("Upload your PO and Bill files and click 'Process' to see the metrics.")
else:
    # 1. ADVANCED MERGE
    # We join bills with specific item names (Bill 2) and header-level bills (Bills 1)
    b_with_items = bill_db[bill_db['Item_Name_Bill'].notna()]
    b_no_items = bill_db[bill_db['Item_Name_Bill'].isna()]

    m_a = pd.merge(b_with_items, po_db, left_on=['PO_Ref', 'Item_Name_Bill'], 
                   right_on=['Purchase Order Number', 'Item Name'], how='inner')
    
    m_b = pd.merge(b_no_items, po_db, left_on='PO_Ref', 
                   right_on='Purchase Order Number', how='inner')

    f_df = pd.concat([m_a, m_b])
    
    # 2. CALCULATIONS
    f_df['Lead_Time'] = (f_df['Bill_Date'] - f_df['Purchase Order Date']).dt.days
    f_df = f_df[f_df['Lead_Time'] >= 0]
    
    # Correcting Invoice Qty: Use Bill Quantity if exists, else assume full PO delivery (for header bills)
    f_df['Invoice_Qty_Final'] = f_df['Inv_Qty'].fillna(f_df['QuantityOrdered'])
    f_df['Weighted_LT_Component'] = f_df['Lead_Time'] * f_df['Invoice_Qty_Final']

    # 3. FILTERS
    st.sidebar.divider()
    vendor_sel = st.sidebar.selectbox("Filter Vendor", ["All"] + sorted(f_df['Vendor Name_y'].unique().tolist()))
    if vendor_sel != "All": f_df = f_df[f_df['Vendor Name_y'] == vendor_sel]

    dr = st.sidebar.date_input("PO Date Range", [f_df['Purchase Order Date'].min(), f_df['Purchase Order Date'].max()])
    if len(dr) == 2:
        f_df = f_df[(f_df['Purchase Order Date'].dt.date >= dr[0]) & (f_df['Purchase Order Date'].dt.date <= dr[1])]

    po_sel = st.sidebar.selectbox("Filter PO Number", ["All"] + sorted(f_df['Purchase Order Number'].unique().tolist()))
    if po_sel != "All": f_df = f_df[f_df['Purchase Order Number'] == po_sel]

    it_sel = st.sidebar.selectbox("Filter Item Name", ["All"] + sorted(f_df['Item Name'].unique().tolist()))
    if it_sel != "All": f_df = f_df[f_df['Item Name'] == it_sel]

    # 4. KPI SUMMARY
    def calc_walt(df):
        total_q = df['Invoice_Qty_Final'].sum()
        return df['Weighted_LT_Component'].sum() / total_q if total_q > 0 else 0

    unique_pos = f_df.drop_duplicates(subset=['Purchase Order Number', 'Item Name'])
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total PO Value", f"₹{unique_pos['Item Total'].sum():,.2f}")
    m2.metric("Number of POs", f_df['Purchase Order Number'].nunique())
    m3.metric("Weighted Avg Lead Time", f"{calc_walt(f_df):.1f} Days")

    # 5. CHARTS
    c1, c2 = st.columns(2)
    with c1:
        chart_po = f_df.groupby('Purchase Order Number').apply(calc_walt).reset_index(name='WALT')
        st.plotly_chart(px.bar(chart_po, x='Purchase Order Number', y='WALT', title="Weighted LT per PO"), use_container_width=True)
    with c2:
        chart_item = f_df.groupby('Item Name').apply(calc_walt).reset_index(name='WALT')
        st.plotly_chart(px.bar(chart_item, x='WALT', y='Item Name', orientation='h', title="Lead Time by Item"), use_container_width=True)

    # 6. TABLE
    st.subheader("📋 Order & Fulfillment Ledger")
    st.dataframe(f_df[['Purchase Order Number', 'Purchase Order Date', 'Vendor Name_y', 'Item Name', 
                       'QuantityOrdered', 'Invoice_Qty_Final', 'Item Total', 'Bill_Date', 'Lead_Time']]
                 .rename(columns={'Vendor Name_y': 'Vendor', 'QuantityOrdered': 'PO Quantity', 
                                  'Invoice_Qty_Final': 'Invoice Quantity', 'Item Total': 'Value'}), 
                 use_container_width=True)
