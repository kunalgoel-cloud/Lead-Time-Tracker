import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Weighted Lead Time Tracker", layout="wide")

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

# --- SIDEBAR: DATA UPLOAD ---
st.sidebar.header("📂 Data Management")
po_file = st.sidebar.file_uploader("Upload Purchase Order CSV", type="csv")
bill_files = st.sidebar.file_uploader("Upload Bill CSVs", type="csv", accept_multiple_files=True)

if st.sidebar.button("Process & Save Data"):
    if po_file:
        df_po = pd.read_csv(po_file)
        df_po = df_po[df_po['Vendor Name'].str.strip().isin(TARGET_VENDORS)]
        df_po['Purchase Order Date'] = pd.to_datetime(df_po['Purchase Order Date'], dayfirst=True)
        df_po['Purchase Order Number'] = df_po['Purchase Order Number'].astype(str).str.strip()
        po_db = df_po.drop_duplicates()

    bill_list = []
    if bill_files:
        for f in bill_files:
            temp_df = pd.read_csv(f)
            
            # --- STANDARDIZATION LOGIC ---
            # 1. Handle PO Reference
            if 'Reference Number' in temp_df.columns: 
                temp_df = temp_df.rename(columns={'Reference Number': 'PO_Ref', 'Date': 'Bill_Date'})
            elif 'Reference Invoice Type' in temp_df.columns: 
                temp_df = temp_df.rename(columns={'Reference Invoice Type': 'PO_Ref', 'Bill Date': 'Bill_Date'})
            
            # 2. Handle Invoice Quantity (Crucial Fix)
            if 'Quantity' in temp_df.columns:
                temp_df['Invoice_Qty'] = pd.to_numeric(temp_df['Quantity'], errors='coerce').fillna(1)
            else:
                # If quantity is missing in the bill file (like Bills (1).csv), default to 1
                temp_df['Invoice_Qty'] = 1
            
            temp_df = temp_df[temp_df['Vendor Name'].str.strip().isin(TARGET_VENDORS)]
            temp_df['Bill_Date'] = pd.to_datetime(temp_df['Bill_Date'], dayfirst=True, errors='coerce')
            temp_df['PO_Ref'] = temp_df['PO_Ref'].astype(str).str.strip()
            
            bill_list.append(temp_df[['PO_Ref', 'Bill_Date', 'Vendor Name', 'Invoice_Qty']])
        
        if bill_list:
            bill_db = pd.concat(bill_list).drop_duplicates()

    with pd.ExcelWriter(DB_FILE) as writer:
        po_db.to_excel(writer, sheet_name="POs", index=False)
        bill_db.to_excel(writer, sheet_name="Bills", index=False)
    st.sidebar.success("Database Updated!")
    st.rerun()

# --- ANALYTICS ENGINE ---
st.title("📊 Supplier Performance: Weighted Lead Time")

if po_db.empty or bill_db.empty:
    st.info("Please upload data to view the dashboard.")
else:
    # 1. MERGE
    merged = pd.merge(bill_db, po_db, left_on='PO_Ref', right_on='Purchase Order Number', how='inner')
    
    # After merge, 'Vendor Name' from PO is 'Vendor Name_y'
    v_col = 'Vendor Name_y' if 'Vendor Name_y' in merged.columns else 'Vendor Name'
    
    # 2. CALC LEAD TIME & WEIGHTS
    merged['Lead_Time'] = (merged['Bill_Date'] - merged['Purchase Order Date']).dt.days
    merged = merged[merged['Lead_Time'] >= 0] 
    merged['weighted_component'] = merged['Lead_Time'] * merged['Invoice_Qty']

    # 3. FILTERS
    st.sidebar.divider()
    vendor_choice = st.sidebar.selectbox("Filter Vendor", ["All"] + sorted(merged[v_col].unique().tolist()))
    f_df = merged.copy()
    if vendor_choice != "All":
        f_df = f_df[f_df[v_col] == vendor_choice]

    # 4. KPI METRICS
    def calc_weighted_avg(df):
        total_q = df['Invoice_Qty'].sum()
        return df['weighted_component'].sum() / total_q if total_q > 0 else 0

    unique_pos = f_df.drop_duplicates(subset=['Purchase Order Number', 'Item Name'])
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total PO Value", f"₹{unique_pos['Item Total'].sum():,.2f}")
    m2.metric("Total POs", f_df['Purchase Order Number'].nunique())
    m3.metric("Weighted Avg Lead Time", f"{calc_weighted_avg(f_df):.1f} Days")

    # 5. CHARTS
    c1, c2 = st.columns(2)
    with c1:
        po_group = f_df.groupby('Purchase Order Number').apply(lambda x: calc_weighted_avg(x)).reset_index(name='W_LT')
        st.plotly_chart(px.bar(po_group, x='Purchase Order Number', y='W_LT', title="Weighted LT per PO"), use_container_width=True)
    with c2:
        item_group = f_df.groupby('Item Name').apply(lambda x: calc_weighted_avg(x)).reset_index(name='W_LT')
        st.plotly_chart(px.bar(item_group, x='W_LT', y='Item Name', orientation='h', title="Weighted LT by Item"), use_container_width=True)

    # 6. TABLE
    st.subheader("Data Detail View")
    st.dataframe(f_df[[
        'Purchase Order Number', 'Purchase Order Date', v_col, 
        'Item Name', 'QuantityOrdered', 'Invoice_Qty', 'Item Total', 'Bill_Date', 'Lead_Time'
    ]].rename(columns={v_col: 'Vendor', 'QuantityOrdered': 'PO Qty', 'Invoice_Qty': 'Invoice Qty'}), use_container_width=True)
