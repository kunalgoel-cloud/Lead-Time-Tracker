import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="PO & Bill Tracker", layout="wide")

# --- INITIALIZE DATABASE ---
if 'po_db' not in st.session_state:
    st.session_state.po_db = pd.DataFrame(columns=['PO_Number', 'Vendor', 'Order_Date', 'Total_Value'])
if 'bill_db' not in st.session_state:
    st.session_state.bill_db = pd.DataFrame(columns=['PO_Number', 'Item', 'Invoice_Date', 'Qty'])

# --- HELPER FUNCTIONS ---
def add_po(number, vendor, date, value):
    if number not in st.session_state.po_db['PO_Number'].values:
        new_row = pd.DataFrame([[number, vendor, date, value]], columns=st.session_state.po_db.columns)
        st.session_state.po_db = pd.concat([st.session_state.po_db, new_row], ignore_index=True)
        st.success(f"PO {number} added!")
    else:
        st.warning("PO Number already exists.")

def add_bill(po_num, item, date, qty):
    # Check for exact duplicate bill entry
    duplicate = st.session_state.bill_db[(st.session_state.bill_db['PO_Number'] == po_num) & 
                                        (st.session_state.bill_db['Item'] == item) & 
                                        (st.session_state.bill_db['Invoice_Date'] == pd.to_datetime(date))]
    if duplicate.empty:
        new_row = pd.DataFrame([[po_num, item, pd.to_datetime(date), qty]], columns=st.session_state.bill_db.columns)
        st.session_state.bill_db = pd.concat([st.session_state.bill_db, new_row], ignore_index=True)
        st.success("Bill added!")
    else:
        st.warning("This specific bill entry already exists.")

# --- SIDEBAR: DATA ENTRY ---
st.sidebar.header("📝 Data Entry")

menu = st.sidebar.radio("Action", ["Add PO", "Add Bill", "Manage/Delete Data"])

if menu == "Add PO":
    with st.sidebar.form("po_form"):
        po_num = st.text_input("PO Number")
        vendor = st.text_input("Vendor Name")
        order_date = st.date_input("Order Date")
        val = st.number_input("Total Value", min_value=0)
        if st.form_submit_button("Submit PO"):
            add_po(po_num, vendor, pd.to_datetime(order_date), val)

elif menu == "Add Bill":
    with st.sidebar.form("bill_form"):
        po_ref = st.selectbox("Select PO Reference", st.session_state.po_db['PO_Number'].unique())
        item_name = st.text_input("Item Name")
        inv_date = st.date_input("Invoice Date")
        qty = st.number_input("Quantity", min_value=1)
        if st.form_submit_button("Submit Bill"):
            add_bill(po_ref, item_name, inv_date, qty)

elif menu == "Manage/Delete Data":
    st.sidebar.subheader("Delete Entries")
    if not st.session_state.po_db.empty:
        po_to_del = st.sidebar.selectbox("Delete PO", st.session_state.po_db['PO_Number'])
        if st.sidebar.button("Confirm Delete PO"):
            st.session_state.po_db = st.session_state.po_db[st.session_state.po_db['PO_Number'] != po_to_del]
            st.session_state.bill_db = st.session_state.bill_db[st.session_state.bill_db['PO_Number'] != po_to_del]
            st.rerun()

# --- MAIN DASHBOARD ---
st.title("📊 Supply Chain Lead Time Dashboard")

if st.session_state.po_db.empty or st.session_state.bill_db.empty:
    st.info("Please add at least one PO and one Bill to see analytics.")
else:
    # JOIN DATA
    df = pd.merge(st.session_state.bill_db, st.session_state.po_db, on="PO_Number")
    df['Lead_Time'] = (df['Invoice_Date'] - df['Order_Date']).dt.days

    # VENDOR DROPDOWN
    vendors = df['Vendor'].unique()
    selected_v = st.selectbox("Filter by Vendor", vendors)
    v_df = df[df['Vendor'] == selected_v]

    # OUTPUTS
    c1, c2 = st.columns(2)
    with c1:
        avg_po = v_df.groupby('PO_Number')['Lead_Time'].mean().reset_index()
        st.plotly_chart(px.bar(avg_po, x='PO_Number', y='Lead_Time', title="Avg Lead Time per PO"), use_container_width=True)
    
    with c2:
        avg_item = v_df.groupby('Item')['Lead_Time'].mean().reset_index()
        st.plotly_chart(px.bar(avg_item, x='Item', y='Lead_Time', title="Avg Lead Time by Item"), use_container_width=True)

    st.subheader("Current Database View")
    st.dataframe(v_df)
