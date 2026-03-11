import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Vendor Performance Dashboard", layout="wide")

# --- CONFIG ---
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

# --- SIDEBAR: UPLOADS ---
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
st.title("📊 Supplier Lead Time & Value Tracker")

if po_db.empty or bill_db.empty:
    st.info("Please upload data to view the dashboard.")
else:
    # 1. MERGE & CLEAN
    merged = pd.merge(bill_db, po_db, left_on='PO_Ref', right_on='Purchase Order Number', how='inner')
    merged['Lead_Time'] = (merged['Bill_Date'] - merged['Purchase Order Date']).dt.days
    merged = merged[merged['Lead_Time'] >= 0] 

    # DYNAMIC COLUMN MAPPING (Handles suffixes like _x or _y)
    def get_col(base_name, df):
        if f"{base_name}_y" in df.columns: return f"{base_name}_y"
        if f"{base_name}_x" in df.columns: return f"{base_name}_x"
        return base_name

    item_col = get_col('Item Name', merged)
    vendor_col = get_col('Vendor Name', merged)
    val_col = get_col('Item Total', merged)
    qty_col = get_col('QuantityOrdered', merged)

    # 2. FILTERS
    st.sidebar.divider()
    vendor_choice = st.sidebar.selectbox("Filter Vendor", ["All"] + sorted(merged[vendor_col].unique().tolist()))
    f_df = merged.copy()
    if vendor_choice != "All":
        f_df = f_df[f_df[vendor_col] == vendor_choice]

    dr = st.sidebar.date_input("PO Date Range", [f_df['Purchase Order Date'].min(), f_df['Purchase Order Date'].max()])
    if len(dr) == 2:
        f_df = f_df[(f_df['Purchase Order Date'].dt.date >= dr[0]) & (f_df['Purchase Order Date'].dt.date <= dr[1])]

    selected_po = st.sidebar.selectbox("Filter PO", ["All"] + sorted(f_df['Purchase Order Number'].unique().tolist()))
    if selected_po != "All":
        f_df = f_df[f_df['Purchase Order Number'] == selected_po]

    selected_item = st.sidebar.selectbox("Filter Item", ["All"] + sorted(f_df[item_col].unique().tolist()))
    if selected_item != "All":
        f_df = f_df[f_df[item_col] == selected_item]

    # 3. TOP METRICS
    # Deduplicate to get accurate PO totals
    unique_entries = f_df.drop_duplicates(subset=['Purchase Order Number', item_col])
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total PO Value", f"₹{unique_entries[val_col].sum():,.2f}")
    m2.metric("Total POs", f_df['Purchase Order Number'].nunique())
    m3.metric("Avg Lead Time", f"{f_df['Lead_Time'].mean():.1f} Days")

    # 4. CHARTS
    c1, c2 = st.columns(2)
    with c1:
        po_chart = f_df.groupby('Purchase Order Number')['Lead_Time'].mean().reset_index()
        st.plotly_chart(px.bar(po_chart, x='Purchase Order Number', y='Lead_Time', title="Avg Lead Time per PO"), use_container_width=True)
    with c2:
        item_chart = f_df.groupby(item_col)['Lead_Time'].mean().reset_index()
        st.plotly_chart(px.bar(item_chart, x='Lead_Time', y=item_col, orientation='h', title="Avg Lead Time by Item"), use_container_width=True)

    # 5. TABLE
    st.subheader("Data Detail View")
    final_table = f_df[['Purchase Order Number', 'Purchase Order Date', vendor_col, item_col, qty_col, val_col, 'Bill_Date', 'Lead_Time']]
    st.dataframe(final_table.rename(columns={vendor_col: 'Vendor', item_col: 'Item', val_col: 'Value', qty_col: 'Qty'}), use_container_width=True)

if st.sidebar.button("🗑️ Reset Database"):
    if os.path.exists(DB_FILE): os.remove(DB_FILE)
    st.rerun()
