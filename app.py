import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Weighted Lead Time Tracker", layout="wide")

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
    if po_file:
        df_po = pd.read_csv(po_file)
        df_po['Vendor Name'] = df_po['Vendor Name'].str.strip()
        df_po = df_po[df_po['Vendor Name'].isin(TARGET_VENDORS)]
        df_po['Purchase Order Date'] = pd.to_datetime(df_po['Purchase Order Date'], dayfirst=True, errors='coerce')
        df_po['Purchase Order Number'] = df_po['Purchase Order Number'].astype(str).str.strip()
        po_db = df_po.drop_duplicates()

    all_bills = []
    if bill_files:
        for f in bill_files:
            temp = pd.read_csv(f)
            
            # 1. Identify PO Reference Column
            ref_col = 'Reference Number' if 'Reference Number' in temp.columns else 'Reference Invoice Type'
            if ref_col not in temp.columns: continue
            
            # 2. Extract Invoice Quantity (Specifically from Bill 2 pattern)
            # We look for 'Quantity' first, then 'Qty'
            actual_qty_col = None
            if 'Quantity' in temp.columns: actual_qty_col = 'Quantity'
            elif 'Qty' in temp.columns: actual_qty_col = 'Qty'
            
            # 3. Create Standardized Bill Record
            std_bill = pd.DataFrame()
            std_bill['PO_Ref'] = temp[ref_col].astype(str).str.strip()
            std_bill['Bill_Date'] = pd.to_datetime(temp['Date'] if 'Date' in temp.columns else temp['Bill Date'], dayfirst=True, errors='coerce')
            std_bill['Vendor Name'] = temp['Vendor Name'].str.strip()
            std_bill['Item_Name_Bill'] = temp['Item Name'] if 'Item Name' in temp.columns else None
            
            if actual_qty_col:
                std_bill['Inv_Qty'] = pd.to_numeric(temp[actual_qty_col], errors='coerce')
            else:
                std_bill['Inv_Qty'] = None # To be filled from PO for header bills
            
            std_bill = std_bill[std_bill['Vendor Name'].isin(TARGET_VENDORS)]
            all_bills.append(std_bill)
        
        if all_bills:
            bill_db = pd.concat(all_bills).drop_duplicates()

    with pd.ExcelWriter(DB_FILE) as writer:
        po_db.to_excel(writer, sheet_name="POs", index=False)
        bill_db.to_excel(writer, sheet_name="Bills", index=False)
    st.sidebar.success("Database Rebuilt!")
    st.rerun()

# --- ANALYTICS ENGINE ---
st.title("📊 Supplier Performance: Weighted Lead Time")

if po_db.empty or bill_db.empty:
    st.info("Upload your PO and Bill files and click 'Process' to see the metrics.")
else:
    # 1. MERGE LOGIC (Handling Item-level vs Header-level bills)
    # Check if we have item-level info to merge on
    if 'Item_Name_Bill' in bill_db.columns and bill_db['Item_Name_Bill'].notna().any():
        item_bills = bill_db[bill_db['Item_Name_Bill'].notna()]
        header_bills = bill_db[bill_db['Item_Name_Bill'].isna()]
        
        merged_items = pd.merge(item_bills, po_db, left_on=['PO_Ref', 'Item_Name_Bill'], 
                                right_on=['Purchase Order Number', 'Item Name'], how='inner')
        merged_headers = pd.merge(header_bills, po_db, left_on='PO_Ref', 
                                  right_on='Purchase Order Number', how='inner')
        f_df = pd.concat([merged_items, merged_headers])
    else:
        f_df = pd.merge(bill_db, po_db, left_on='PO_Ref', right_on='Purchase Order Number', how='inner')

    # 2. CALCULATIONS
    f_df['Lead_Time'] = (f_df['Bill_Date'] - f_df['Purchase Order Date']).dt.days
    f_df = f_df[f_df['Lead_Time'] >= 0]
    
    # Fill missing Invoice Qty with PO Qty (for Bills 1)
    f_df['Inv_Qty_Final'] = f_df['Inv_Qty'].fillna(f_df['QuantityOrdered'])
    f_df['W_Comp'] = f_df['Lead_Time'] * f_df['Inv_Qty_Final']

    # 3. KPI CALCULATIONS
    def get_walt(df):
        total_q = df['Inv_Qty_Final'].sum()
        return df['W_Comp'].sum() / total_q if total_q > 0 else 0

    m1, m2, m3 = st.columns(3)
    unique_pos = f_df.drop_duplicates(subset=['Purchase Order Number', 'Item Name'])
    m1.metric("Total Order Value", f"₹{unique_pos['Item Total'].sum():,.2f}")
    m2.metric("Total POs", f_df['Purchase Order Number'].nunique())
    m3.metric("Weighted Avg Lead Time", f"{get_walt(f_df):.1f} Days")

    # 4. VISUALS
    c1, c2 = st.columns(2)
    with c1:
        po_group = f_df.groupby('Purchase Order Number').apply(get_walt).reset_index(name='WLT')
        st.plotly_chart(px.bar(po_group, x='Purchase Order Number', y='WLT', title="Weighted LT per PO"), use_container_width=True)
    with c2:
        item_group = f_df.groupby('Item Name').apply(get_walt).reset_index(name='WLT')
        st.plotly_chart(px.bar(item_group, x='WLT', y='Item Name', orientation='h', title="Efficiency by Item"), use_container_width=True)

    # 5. TABLE
    st.subheader("Fulfillment Record")
    st.dataframe(f_df[['Purchase Order Number', 'Purchase Order Date', 'Vendor Name_y', 'Item Name', 
                       'QuantityOrdered', 'Inv_Qty_Final', 'Item Total', 'Bill_Date', 'Lead_Time']]
                 .rename(columns={'Vendor Name_y': 'Vendor', 'QuantityOrdered': 'PO Qty', 
                                  'Inv_Qty_Final': 'Invoice Qty', 'Item Total': 'Value'}), 
                 use_container_width=True)

if st.sidebar.button("🗑️ Reset All"):
    if os.path.exists(DB_FILE): os.remove(DB_FILE)
    st.rerun()
