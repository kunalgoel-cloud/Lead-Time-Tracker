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
            # Normalize Invoice Qty column names based on your files
            if 'Quantity' in temp_df.columns:
                temp_df = temp_df.rename(columns={'Quantity': 'Inv_Qty'})
            # Normalize Reference Number
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
st.title("📊 Supplier Performance: Weighted Lead Time")

if po_db.empty or bill_db.empty:
    st.info("Please upload data to view the dashboard.")
else:
    # 1. MERGE
    merged = pd.merge(bill_db, po_db, left_on='PO_Ref', right_on='Purchase Order Number', how='inner')
    merged['Lead_Time'] = (merged['Bill_Date'] - merged['Purchase Order Date']).dt.days
    merged = merged[merged['Lead_Time'] >= 0] 

    # Dynamic Column Mapping
    def get_col(base_name, df):
        if f"{base_name}_y" in df.columns: return f"{base_name}_y"
        if f"{base_name}_x" in df.columns: return f"{base_name}_x"
        return base_name

    item_col = get_col('Item Name', merged)
    vendor_col = get_col('Vendor Name', merged)
    val_col = get_col('Item Total', merged)
    po_qty_col = get_col('QuantityOrdered', merged)
    inv_qty_col = 'Inv_Qty' if 'Inv_Qty' in merged.columns else 'Quantity'

    # 2. WEIGHTED CALCULATION
    # Calculation: (Lead Time * Invoice Qty) 
    merged['weighted_component'] = merged['Lead_Time'] * merged[inv_qty_col]

    # 3. FILTERS
    st.sidebar.divider()
    vendor_choice = st.sidebar.selectbox("Filter Vendor", ["All"] + sorted(merged[vendor_col].unique().tolist()))
    f_df = merged.copy()
    if vendor_choice != "All":
        f_df = f_df[f_df[vendor_col] == vendor_choice]

    dr = st.sidebar.date_input("PO Date Range", [f_df['Purchase Order Date'].min(), f_df['Purchase Order Date'].max()])
    if len(dr) == 2:
        f_df = f_df[(f_df['Purchase Order Date'].dt.date >= dr[0]) & (f_df['Purchase Order Date'].dt.date <= dr[1])]

    # 4. KPI METRICS (Weighted)
    def calc_weighted_avg(df):
        total_qty = df[inv_qty_col].sum()
        if total_qty == 0: return 0
        return df['weighted_component'].sum() / total_qty

    unique_pos = f_df.drop_duplicates(subset=['Purchase Order Number', item_col])
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total PO Value", f"₹{unique_pos[val_col].sum():,.2f}")
    m2.metric("Total POs", f_df['Purchase Order Number'].nunique())
    m3.metric("Weighted Avg Lead Time", f"{calc_weighted_avg(f_df):.1f} Days")

    # 5. CHARTS
    c1, c2 = st.columns(2)
    with c1:
        # Weighted LT per PO
        po_group = f_df.groupby('Purchase Order Number').apply(lambda x: calc_weighted_avg(x)).reset_index(name='W_LT')
        st.plotly_chart(px.bar(po_group, x='Purchase Order Number', y='W_LT', title="Weighted Lead Time per PO"), use_container_width=True)
    with c2:
        # Weighted LT per Item
        item_group = f_df.groupby(item_col).apply(lambda x: calc_weighted_avg(x)).reset_index(name='W_LT')
        st.plotly_chart(px.bar(item_group, x='W_LT', y=item_col, orientation='h', title="Weighted Lead Time by Item"), use_container_width=True)

    # 6. TABLE
    st.subheader("Data Detail View")
    final_table = f_df[[
        'Purchase Order Number', 'Purchase Order Date', vendor_col, 
        item_col, po_qty_col, inv_qty_col, val_col, 'Bill_Date', 'Lead_Time'
    ]]
    st.dataframe(final_table.rename(columns={
        vendor_col: 'Vendor', item_col: 'Item', 
        val_col: 'Value', po_qty_col: 'PO Qty', inv_qty_col: 'Invoice Qty'
    }), use_container_width=True)
