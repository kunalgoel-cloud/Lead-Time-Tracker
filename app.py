import streamlit as st
import pandas as pd
import plotly.express as px

# --- APP CONFIG ---
st.set_page_config(page_title="Supplier Lead Time Tracker", layout="wide")
st.title("📦 Supplier Lead Time Analytics")

# --- MOCK DATA GENERATOR (Replace with st.file_uploader for your CSVs) ---
@st.cache_data
def load_data():
    # Example PO Data
    po_data = pd.DataFrame({
        'PO_Number': ['PO-001', 'PO-002', 'PO-003'],
        'Vendor': ['Acme Corp', 'Globex', 'Acme Corp'],
        'Order_Date': pd.to_datetime(['2024-01-01', '2024-01-05', '2024-01-10']),
        'Total_Value': [1000, 5000, 2000]
    })
    
    # Example Bill/Invoice Data
    bill_data = pd.DataFrame({
        'PO_Number': ['PO-001', 'PO-002', 'PO-002', 'PO-003'],
        'Item': ['Widget A', 'Gadget B', 'Gadget B', 'Widget A'],
        'Invoice_Date': pd.to_datetime(['2024-01-10', '2024-01-20', '2024-01-25', '2024-01-15']),
        'Qty': [10, 50, 50, 20]
    })
    return po_data, bill_data

po_df, bill_df = load_data()

# --- DATA PROCESSING ---
# Join Bills to POs
merged_df = pd.merge(bill_df, po_df, on="PO_Number")

# Calculate Lead Time (Days)
merged_df['Lead_Time'] = (merged_df['Invoice_Date'] - merged_df['Order_Date']).dt.days

# --- SIDEBAR FILTERS ---
st.sidebar.header("Filters")
vendor_list = po_df['Vendor'].unique()
selected_vendor = st.sidebar.selectbox("Select Vendor", vendor_list)

# Filter data based on selection
filtered_df = merged_df[merged_df['Vendor'] == selected_vendor]

# --- DASHBOARD LAYOUT ---
col1, col2 = st.columns(2)

with col1:
    st.subheader(f"Avg Lead Time: {selected_vendor}")
    # Group by PO to show performance per order
    po_avg = filtered_df.groupby('PO_Number')['Lead_Time'].mean().reset_index()
    fig_po = px.bar(po_avg, x='PO_Number', y='Lead_Time', 
                    labels={'Lead_Time': 'Days'}, title="Lead Time per Purchase Order")
    st.plotly_chart(fig_po, use_container_width=True)

with col2:
    st.subheader("Lead Time by Item")
    # Metric of average lead time of supplier by item
    item_avg = filtered_df.groupby('Item')['Lead_Time'].mean().reset_index()
    fig_item = px.bar(item_avg, x='Item', y='Lead_Time', 
                      color='Lead_Time', color_continuous_scale='Reds',
                      title="Avg Days to Deliver by SKU")
    st.plotly_chart(fig_item, use_container_width=True)

st.divider()

# --- DATA VIEW ---
st.subheader("Raw Fulfillment Data")
st.dataframe(filtered_df[['PO_Number', 'Item', 'Order_Date', 'Invoice_Date', 'Lead_Time']], use_container_width=True)
