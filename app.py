import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Lead Time Tracker", layout="wide")

DB_FILE = "supplier_data.xlsx"

# --- DATABASE ENGINE ---
def load_db():
    if os.path.exists(DB_FILE):
        pos = pd.read_excel(DB_FILE, sheet_name="POs")
        bills = pd.read_excel(DB_FILE, sheet_name="Bills")
        return pos, bills
    return pd.DataFrame(columns=['PO_Number', 'Vendor', 'Order_Date', 'Total_Value']), \
           pd.DataFrame(columns=['PO_Number', 'Item', 'Invoice_Date', 'Qty', 'Value'])

def save_db(po_df, bill_df):
    with pd.ExcelWriter(DB_FILE) as writer:
        po_df.to_excel(writer, sheet_name="POs", index=False)
        bill_df.to_excel(writer, sheet_name="Bills", index=False)

po_db, bill_db = load_db()

# --- SIDEBAR: BULK UPLOAD ---
st.sidebar.header("📂 Bulk Data Upload")
uploaded_po = st.sidebar.file_uploader("Upload POs (CSV/XLSX)", type=['csv', 'xlsx'])
uploaded_bill = st.sidebar.file_uploader("Upload Bills (CSV/XLSX)", type=['csv', 'xlsx'])

if st.sidebar.button("Process & Append Uploads"):
    if uploaded_po:
        new_pos = pd.read_csv(uploaded_po) if uploaded_po.name.endswith('.csv') else pd.read_excel(uploaded_po)
        new_pos['Order_Date'] = pd.to_datetime(new_pos['Order_Date'])
        # Deduplicate based on PO_Number
        po_db = pd.concat([po_db, new_pos]).drop_duplicates(subset=['PO_Number'], keep='first')
    
    if uploaded_bill:
        new_bills = pd.read_csv(uploaded_bill) if uploaded_bill.name.endswith('.csv') else pd.read_excel(uploaded_bill)
        new_bills['Invoice_Date'] = pd.to_datetime(new_bills['Invoice_Date'])
        # Deduplicate based on PO, Item, and Date
        bill_db = pd.concat([bill_db, new_bills]).drop_duplicates(subset=['PO_Number', 'Item', 'Invoice_Date'], keep='first')
    
    save_db(po_db, bill_db)
    st.sidebar.success("Database Updated!")
    st.rerun()

# --- DATA MANAGEMENT ---
st.sidebar.divider()
if st.sidebar.button("🗑️ Clear All Data"):
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    st.rerun()

# --- ANALYTICS ENGINE ---
st.title("🚀 Supplier Lead Time Analytics")

if po_db.empty or bill_db.empty:
    st.warning("Please upload PO and Bill files to begin. Ensure columns match: [PO_Number, Vendor, Order_Date] and [PO_Number, Item, Invoice_Date, Qty].")
else:
    # Logic: Join and Calculate
    merged = pd.merge(bill_db, po_db, on="PO_Number", how="inner")
    merged['Lead_Time'] = (pd.to_datetime(merged['Invoice_Date']) - pd.to_datetime(merged['Order_Date'])).dt.days

    # 1. Vendor Dropdown
    vendor_choice = st.selectbox("Select Vendor to Analyze", options=merged['Vendor'].unique())
    v_df = merged[merged['Vendor'] == vendor_choice]

    # 2. Metrics & Charts
    m1, m2 = st.columns(2)
    
    with m1:
        # View of avg lead time for each PO
        po_avg = v_df.groupby('PO_Number')['Lead_Time'].mean().reset_index()
        fig1 = px.bar(po_avg, x='PO_Number', y='Lead_Time', title="Average Lead Time per Purchase Order", color_discrete_sequence=['#3366CC'])
        st.plotly_chart(fig1, use_container_width=True)

    with m2:
        # Metric of avg lead time by item
        item_avg = v_df.groupby('Item')['Lead_Time'].mean().reset_index()
        fig2 = px.bar(item_avg, x='Item', y='Lead_Time', title="Lead Time Efficiency by Item", color='Lead_Time', color_continuous_scale='Viridis')
        st.plotly_chart(fig2, use_container_width=True)

    # 3. Data Management Table (Delete option)
    st.subheader("Manage Database Entries")
    tab1, tab2 = st.tabs(["Purchase Orders", "Vendor Bills"])
    
    with tab1:
        st.write("To delete a PO, identify the number and use the sidebar (or clear all).")
        st.dataframe(po_db, use_container_width=True)
        
    with tab2:
        st.dataframe(bill_db, use_container_width=True)
