import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re

st.set_page_config(page_title="Weighted Lead Time Tracker", layout="wide")

# --- CONFIG ---
TARGET_VENDORS = ["Candor Foods Pvt Ltd.", "Evergreen Foods and Snacks Pvt Ltd"]
DB_FILE = "vendor_analytics_db.xlsx"


# ── helpers ────────────────────────────────────────────────────────────────────

def clean_currency(series: pd.Series) -> pd.Series:
    """Strip ₹ symbol, commas and whitespace then cast to float."""
    return (
        series.astype(str)
        .str.replace(r"[₹,\s]", "", regex=True)
        .pipe(pd.to_numeric, errors="coerce")
    )


def load_db():
    if os.path.exists(DB_FILE):
        try:
            return (
                pd.read_excel(DB_FILE, sheet_name="POs"),
                pd.read_excel(DB_FILE, sheet_name="Bills"),
            )
        except Exception:
            pass
    return pd.DataFrame(), pd.DataFrame()


po_db, bill_db = load_db()

# ── SIDEBAR: DATA UPLOAD ───────────────────────────────────────────────────────
st.sidebar.header("📂 Data Management")
po_file = st.sidebar.file_uploader("Upload Purchase Order CSV", type="csv")
bill_files = st.sidebar.file_uploader(
    "Upload Bill CSVs", type="csv", accept_multiple_files=True
)

if st.sidebar.button("Process & Update Data"):
    # ── 1. Process PO file ──────────────────────────────────────────────────
    if po_file:
        df_po = pd.read_csv(po_file)
        df_po["Vendor Name"] = df_po["Vendor Name"].str.strip()
        df_po = df_po[df_po["Vendor Name"].isin(TARGET_VENDORS)].copy()
        df_po["Purchase Order Date"] = pd.to_datetime(
            df_po["Purchase Order Date"], dayfirst=True, errors="coerce"
        )
        df_po["Purchase Order Number"] = (
            df_po["Purchase Order Number"].astype(str).str.strip()
        )
        df_po["Item Name"] = df_po["Item Name"].str.strip().str.lower()
        df_po["Item Total"] = pd.to_numeric(df_po["Item Total"], errors="coerce")
        df_po["QuantityOrdered"] = pd.to_numeric(
            df_po["QuantityOrdered"], errors="coerce"
        )
        po_db = df_po.drop_duplicates()

    # ── 2. Process Bill files ───────────────────────────────────────────────
    all_bills = []
    if bill_files:
        for f in bill_files:
            temp = pd.read_csv(f)
            temp.columns = temp.columns.str.strip()
            vendor_col = "Vendor Name" if "Vendor Name" in temp.columns else None
            if vendor_col is None:
                continue
            temp[vendor_col] = temp[vendor_col].str.strip()
            temp = temp[temp[vendor_col].isin(TARGET_VENDORS)].copy()
            if temp.empty:
                continue

            # ── Bills__1_ pattern: header-level, has Reference Number ──────
            # Columns: BILL_ID, Date, Bill#, Vendor Name, Status, Amount,
            #          Reference Number, Item Price
            if "Reference Number" in temp.columns and "Date" in temp.columns and "BILL_ID" in temp.columns:
                std = pd.DataFrame()
                std["PO_Ref"] = (
                    temp["Reference Number"].astype(str).str.strip()
                )
                std["Bill_Date"] = pd.to_datetime(
                    temp["Date"], dayfirst=True, errors="coerce"
                )
                std["Vendor Name"] = temp[vendor_col]
                std["Item_Name_Bill"] = None          # no item-level detail
                std["Inv_Qty"] = None                 # will fall back to PO qty
                std["Bill_Amount"] = clean_currency(temp["Amount"])
                std["Invoice_Number"] = temp["Bill#"].astype(str).str.strip() if "Bill#" in temp.columns else None
                std = std[std["PO_Ref"].notna() & (std["PO_Ref"] != "nan")]
                all_bills.append(std)

            # ── Bill__2_ pattern: item-level, no PO reference ─────────────
            # Columns: Bill Date, Vendor Name, Bill Number, Account,
            #          CF.Item Price, Reference Invoice Type, Item Name,
            #          Item Total, Quantity
            elif "Bill Date" in temp.columns and "Item Name" in temp.columns:
                std = pd.DataFrame()
                std["PO_Ref"] = None                  # no PO ref in this file
                std["Bill_Date"] = pd.to_datetime(
                    temp["Bill Date"], dayfirst=True, errors="coerce"
                )
                std["Vendor Name"] = temp[vendor_col]
                std["Item_Name_Bill"] = (
                    temp["Item Name"].str.strip().str.lower()
                )
                std["Inv_Qty"] = pd.to_numeric(
                    temp["Quantity"], errors="coerce"
                )
                std["Bill_Amount"] = pd.to_numeric(
                    temp["Item Total"], errors="coerce"
                )
                std["Invoice_Number"] = temp["Bill Number"].astype(str).str.strip() if "Bill Number" in temp.columns else None
                all_bills.append(std)

    if all_bills:
        bill_db = pd.concat(all_bills, ignore_index=True).drop_duplicates()

    # ── Persist ─────────────────────────────────────────────────────────────
    if not po_db.empty and not bill_db.empty:
        with pd.ExcelWriter(DB_FILE, engine="openpyxl") as writer:
            po_db.to_excel(writer, sheet_name="POs", index=False)
            bill_db.to_excel(writer, sheet_name="Bills", index=False)
        st.sidebar.success("✅ Database rebuilt successfully!")
        st.rerun()
    else:
        st.sidebar.warning("⚠️ No matching vendor data found. Check your files.")

# ── ANALYTICS ENGINE ───────────────────────────────────────────────────────────
st.title("📊 Supplier Performance: Weighted Lead Time")

if po_db.empty or bill_db.empty:
    st.info(
        "Upload your PO and Bill files in the sidebar and click "
        "**Process & Update Data** to see the metrics."
    )
    st.stop()

# Normalise item names in po_db (in case loaded from Excel without lowercasing)
if "Item Name" not in po_db.columns:
    st.warning("PO data is missing expected columns. Please re-upload and reprocess.")
    st.stop()
po_db["Item Name"] = po_db["Item Name"].astype(str).str.strip().str.lower()
po_db["Purchase Order Date"] = pd.to_datetime(po_db["Purchase Order Date"], errors="coerce")

# Ensure bill_db Bill_Date is datetime after Excel reload
bill_db["Bill_Date"] = pd.to_datetime(bill_db["Bill_Date"], errors="coerce")

# ── MERGE LOGIC ────────────────────────────────────────────────────────────────
#
#  Bills__1_  → has PO_Ref but no Item_Name_Bill
#              → merge on PO_Ref + Vendor Name
#              → use PO QuantityOrdered as invoice qty
#
#  Bill__2_   → has Item_Name_Bill but no PO_Ref
#              → merge on Item_Name_Bill + Vendor Name (latest PO per item)
#

# Ensure expected columns exist (they may be absent if loaded from an older Excel snapshot)
for col in ["PO_Ref", "Item_Name_Bill", "Inv_Qty", "Bill_Amount", "Vendor Name", "Bill_Date", "Invoice_Number"]:
    if col not in bill_db.columns:
        bill_db[col] = None

ref_bills  = bill_db[bill_db["PO_Ref"].notna() & (bill_db["PO_Ref"].astype(str) != "nan")].copy()
item_bills = bill_db[bill_db["Item_Name_Bill"].notna()].copy()

merged_parts = []

# Part A: reference-based (Bills__1_)
if not ref_bills.empty:
    merged_a = pd.merge(
        ref_bills,
        po_db,
        left_on=["PO_Ref", "Vendor Name"],
        right_on=["Purchase Order Number", "Vendor Name"],
        how="inner",
    )
    merged_parts.append(merged_a)

# Part B: item-name-based (Bill__2_)
if not item_bills.empty:
    merged_b = pd.merge(
        item_bills,
        po_db,
        left_on=["Item_Name_Bill", "Vendor Name"],
        right_on=["Item Name", "Vendor Name"],
        how="inner",
        suffixes=("_bill", ""),
    )
    merged_parts.append(merged_b)

if not merged_parts:
    st.warning("No matching records found between POs and Bills.")
    st.stop()

f_df = pd.concat(merged_parts, ignore_index=True)

# Guarantee Item Name column exists (suffix issues across concat paths)
if "Item Name" not in f_df.columns:
    if "Item Name_bill" in f_df.columns:
        f_df["Item Name"] = f_df["Item Name_bill"]
    elif "Item_Name_Bill" in f_df.columns:
        f_df["Item Name"] = f_df["Item_Name_Bill"]
    else:
        f_df["Item Name"] = "Unknown"
# Fill any NaN Item Names from Item_Name_Bill fallback
if "Item_Name_Bill" in f_df.columns:
    f_df["Item Name"] = f_df["Item Name"].fillna(f_df["Item_Name_Bill"])

# ── CALCULATIONS ───────────────────────────────────────────────────────────────
f_df["Lead_Time"] = (
    f_df["Bill_Date"] - f_df["Purchase Order Date"]
).dt.days
f_df = f_df[f_df["Lead_Time"] >= 0].copy()

# Invoice qty: use Inv_Qty if available, else fall back to PO QuantityOrdered
f_df["Inv_Qty_Final"] = f_df["Inv_Qty"].fillna(f_df["QuantityOrdered"])
f_df["W_Comp"] = f_df["Lead_Time"] * f_df["Inv_Qty_Final"]

# Restore display-friendly item name
f_df["Item Name Display"] = f_df["Item Name"].str.title()

# ── KPI HELPER ─────────────────────────────────────────────────────────────────
def get_walt(df: pd.DataFrame) -> float:
    total_q = df["Inv_Qty_Final"].sum()
    return df["W_Comp"].sum() / total_q if total_q > 0 else 0.0


# ── FILTERS ────────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    vendor_choice = st.selectbox("Filter by Vendor", ["All Vendors"] + TARGET_VENDORS)

# Derive min/max dates from PO Date for the date range picker
min_date = f_df["Purchase Order Date"].min().date()
max_date = f_df["Purchase Order Date"].max().date()

with col_f2:
    date_from = st.date_input("PO Date From", value=min_date, min_value=min_date, max_value=max_date)
with col_f3:
    date_to = st.date_input("PO Date To", value=max_date, min_value=min_date, max_value=max_date)

# Apply filters
view_df = f_df.copy()
if vendor_choice != "All Vendors":
    view_df = view_df[view_df["Vendor Name"] == vendor_choice]
view_df = view_df[
    (view_df["Purchase Order Date"].dt.date >= date_from) &
    (view_df["Purchase Order Date"].dt.date <= date_to)
]

if view_df.empty:
    st.warning("No data available for the selected filters.")
    st.stop()

# ── KPI METRICS ────────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
unique_po_items = view_df.drop_duplicates(subset=["Purchase Order Number", "Item Name"])
m1.metric("Total Order Value (₹)", f"₹{unique_po_items['Item Total'].sum():,.0f}")
m2.metric("Total POs", view_df["Purchase Order Number"].nunique())
m3.metric("Total SKUs", view_df["Item Name"].nunique())
m4.metric("Weighted Avg Lead Time", f"{get_walt(view_df):.1f} days")

st.divider()

# ── CHARTS ─────────────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

with c1:
    po_group = (
        view_df.groupby("Purchase Order Number")
        .apply(get_walt)
        .reset_index(name="Weighted Lead Time (days)")
    )
    fig1 = px.bar(
        po_group,
        x="Purchase Order Number",
        y="Weighted Lead Time (days)",
        title="Weighted Lead Time per PO",
        color="Weighted Lead Time (days)",
        color_continuous_scale="RdYlGn_r",
    )
    fig1.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig1, use_container_width=True)

with c2:
    item_group = (
        view_df.groupby("Item Name Display")
        .apply(get_walt)
        .reset_index(name="Weighted Lead Time (days)")
        .sort_values("Weighted Lead Time (days)", ascending=True)
    )
    fig2 = px.bar(
        item_group,
        x="Weighted Lead Time (days)",
        y="Item Name Display",
        orientation="h",
        title="Lead Time Efficiency by Item",
        color="Weighted Lead Time (days)",
        color_continuous_scale="RdYlGn_r",
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── VENDOR COMPARISON (only when "All Vendors" selected) ──────────────────────
if vendor_choice == "All Vendors":
    st.subheader("Vendor Comparison")
    vendor_group = (
        f_df.groupby("Vendor Name")
        .apply(get_walt)
        .reset_index(name="Weighted Lead Time (days)")
    )
    fig3 = px.bar(
        vendor_group,
        x="Vendor Name",
        y="Weighted Lead Time (days)",
        title="Weighted Lead Time by Vendor",
        color="Vendor Name",
    )
    st.plotly_chart(fig3, use_container_width=True)

# ── FULFILLMENT TABLE ──────────────────────────────────────────────────────────
st.subheader("📋 Fulfillment Record")

# Build Invoice_Number column (may be missing on older cached Excel)
if "Invoice_Number" not in view_df.columns:
    view_df = view_df.copy()
    view_df["Invoice_Number"] = "-"
view_df["Invoice_Number"] = view_df["Invoice_Number"].fillna("-")

display_cols = {
    "Purchase Order Number": "PO Number",
    "Invoice_Number": "Invoice Number",
    "Purchase Order Date": "PO Date",
    "Vendor Name": "Vendor",
    "Item Name Display": "Item",
    "QuantityOrdered": "PO Qty",
    "Inv_Qty_Final": "Invoice Qty",
    "Item Total": "PO Value (₹)",
    "Bill_Date": "Bill Date",
    "Lead_Time": "Lead Time (days)",
}

table_df = view_df[list(display_cols.keys())].rename(columns=display_cols).copy()
table_df["PO Date"] = table_df["PO Date"].dt.strftime("%d-%b-%Y")
table_df["Bill Date"] = table_df["Bill Date"].dt.strftime("%d-%b-%Y")
table_df["PO Value (₹)"] = table_df["PO Value (₹)"].apply(
    lambda x: f"₹{x:,.0f}" if pd.notna(x) else "-"
)

st.dataframe(table_df, use_container_width=True)

# ── DOWNLOAD ───────────────────────────────────────────────────────────────────
csv_bytes = table_df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Download Fulfillment Report (CSV)",
    data=csv_bytes,
    file_name="fulfillment_report.csv",
    mime="text/csv",
)

# ── REMOVE PO DATA ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("🗑️ Remove PO Data")
st.caption("Select one or more POs to permanently delete all their bill records from the database.")

all_pos = sorted(f_df["Purchase Order Number"].dropna().unique().tolist())
pos_to_remove = st.multiselect(
    "Select PO(s) to remove",
    options=all_pos,
    placeholder="Choose PO numbers...",
)

if pos_to_remove:
    affected = f_df[f_df["Purchase Order Number"].isin(pos_to_remove)]
    st.warning(
        f"This will remove **{len(affected)} record(s)** across "
        f"**{affected['Item Name Display'].nunique()} SKU(s)** "
        f"for: {', '.join(pos_to_remove)}"
    )
    if st.button("⚠️ Confirm Removal", type="primary"):
        # Remove matching PO rows from po_db and corresponding bill rows
        po_db_new = po_db[~po_db["Purchase Order Number"].isin(pos_to_remove)].copy()

        # Remove from bill_db: rows where PO_Ref matches (ref-based bills)
        # and rows where Item_Name_Bill matches items in the removed POs (item-based bills)
        removed_items = po_db[po_db["Purchase Order Number"].isin(pos_to_remove)]["Item Name"].unique()
        removed_vendors = po_db[po_db["Purchase Order Number"].isin(pos_to_remove)]["Vendor Name"].unique()

        bill_db_new = bill_db.copy()
        # Drop ref-based rows
        if "PO_Ref" in bill_db_new.columns:
            bill_db_new = bill_db_new[
                ~(bill_db_new["PO_Ref"].isin(pos_to_remove))
            ]
        # Drop item-based rows (same item + vendor combination)
        if "Item_Name_Bill" in bill_db_new.columns:
            bill_db_new = bill_db_new[
                ~(
                    bill_db_new["Item_Name_Bill"].isin(removed_items) &
                    bill_db_new["Vendor Name"].isin(removed_vendors)
                )
            ]

        with pd.ExcelWriter(DB_FILE, engine="openpyxl") as writer:
            po_db_new.to_excel(writer, sheet_name="POs", index=False)
            bill_db_new.to_excel(writer, sheet_name="Bills", index=False)

        st.success(f"✅ Removed data for: {', '.join(pos_to_remove)}")
        st.rerun()

# ── RESET ──────────────────────────────────────────────────────────────────────
st.sidebar.divider()
if st.sidebar.button("🗑️ Reset All Data"):
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    st.rerun()
