import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Weighted Lead Time Tracker", layout="wide")

TARGET_VENDORS = ["Candor Foods Pvt Ltd.", "Evergreen Foods and Snacks Pvt Ltd"]
DB_FILE = "vendor_analytics_db.xlsx"


# ── HELPERS ────────────────────────────────────────────────────────────────────

def clean_currency(series: pd.Series) -> pd.Series:
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
                pd.read_excel(DB_FILE, sheet_name="Bills_Header"),
                pd.read_excel(DB_FILE, sheet_name="Bills_Lines"),
            )
        except Exception:
            pass
    return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


po_db, b1_db, b2_db = load_db()


# ── SIDEBAR ────────────────────────────────────────────────────────────────────
st.sidebar.header("📂 Data Management")
po_file    = st.sidebar.file_uploader("Upload Purchase Order CSV", type="csv")
bill_files = st.sidebar.file_uploader("Upload Bill CSVs", type="csv", accept_multiple_files=True)

if st.sidebar.button("Process & Update Data"):

    if po_file:
        df_po = pd.read_csv(po_file)
        df_po["Vendor Name"] = df_po["Vendor Name"].str.strip()
        df_po = df_po[df_po["Vendor Name"].isin(TARGET_VENDORS)].copy()
        df_po["Purchase Order Date"]   = pd.to_datetime(df_po["Purchase Order Date"], dayfirst=True, errors="coerce")
        df_po["Purchase Order Number"] = df_po["Purchase Order Number"].astype(str).str.strip()
        df_po["Item Name"]             = df_po["Item Name"].str.strip().str.lower()
        df_po["Item Total"]            = pd.to_numeric(df_po["Item Total"],      errors="coerce")
        df_po["QuantityOrdered"]       = pd.to_numeric(df_po["QuantityOrdered"], errors="coerce")
        po_db = df_po.drop_duplicates()

    # TWO FILE TYPES:
    #
    # Bills__1_ (header-level):  BILL_ID, Date(DD/MM/YYYY), Bill#, Vendor Name,
    #                             Status, Amount, Reference Number, Item Price
    #   One row per invoice. Has PO Reference + Invoice Number. NO item/qty detail.
    #
    # Bill__2_  (item-level):    Bill Date(YYYY-MM-DD), Vendor Name, Bill Number,
    #                             Account, CF.Item Price, Reference Invoice Type,
    #                             Item Name, Item Total, Quantity
    #   One row per line item. Has Invoice Number + Item + Qty. NO PO reference.
    #
    # CORRECT CHAIN:
    #   Bill__2_ lines --(Invoice_Number + Vendor)--> Bills__1_ header
    #                  --(PO_Ref + Item + Vendor)---> PO master

    new_b1_list, new_b2_list = [], []

    if bill_files:
        for f in bill_files:
            temp = pd.read_csv(f)
            temp.columns = temp.columns.str.strip()
            if "Vendor Name" not in temp.columns:
                continue
            temp["Vendor Name"] = temp["Vendor Name"].str.strip()
            temp = temp[temp["Vendor Name"].isin(TARGET_VENDORS)].copy()
            if temp.empty:
                continue

            # Identify Bills__1_ by presence of BILL_ID + Reference Number
            if "BILL_ID" in temp.columns and "Reference Number" in temp.columns:
                b1 = pd.DataFrame()
                b1["Invoice_Number"] = temp["Bill#"].astype(str).str.strip()
                b1["Vendor Name"]    = temp["Vendor Name"]
                b1["PO_Ref"]         = temp["Reference Number"].astype(str).str.strip()
                b1["Bill_Date"]      = pd.to_datetime(temp["Date"], dayfirst=True, errors="coerce")
                b1["Bill_Amount"]    = clean_currency(temp["Amount"])
                b1 = b1[b1["PO_Ref"].notna() & ~b1["PO_Ref"].isin(["nan", "None", ""])]
                new_b1_list.append(b1)

            # Identify Bill__2_ by presence of Bill Date + Item Name + Bill Number
            elif "Bill Date" in temp.columns and "Item Name" in temp.columns and "Bill Number" in temp.columns:
                b2 = pd.DataFrame()
                b2["Invoice_Number"] = temp["Bill Number"].astype(str).str.strip()
                b2["Vendor Name"]    = temp["Vendor Name"]
                # Bill__2_ dates are YYYY-MM-DD — must use dayfirst=False
                b2["Bill_Date"]      = pd.to_datetime(temp["Bill Date"], dayfirst=False, errors="coerce")
                b2["Item_Name_Bill"] = temp["Item Name"].str.strip().str.lower()
                b2["Inv_Qty"]        = pd.to_numeric(temp["Quantity"],   errors="coerce")
                b2["Bill_Amount"]    = pd.to_numeric(temp["Item Total"], errors="coerce")
                new_b2_list.append(b2)

    if new_b1_list:
        b1_db = pd.concat(new_b1_list, ignore_index=True).drop_duplicates()
    if new_b2_list:
        b2_db = pd.concat(new_b2_list, ignore_index=True).drop_duplicates()

    if not po_db.empty and not b1_db.empty and not b2_db.empty:
        with pd.ExcelWriter(DB_FILE, engine="openpyxl") as writer:
            po_db.to_excel(writer, sheet_name="POs",          index=False)
            b1_db.to_excel(writer, sheet_name="Bills_Header", index=False)
            b2_db.to_excel(writer, sheet_name="Bills_Lines",  index=False)
        st.sidebar.success("✅ Database rebuilt successfully!")
        st.rerun()
    else:
        st.sidebar.warning("⚠️ Could not find all required file types. Check uploads.")


# ── ANALYTICS ─────────────────────────────────────────────────────────────────
st.title("📊 Supplier Performance: Weighted Lead Time")

if po_db.empty or b1_db.empty or b2_db.empty:
    st.info("Upload your PO CSV and both Bill CSVs, then click **Process & Update Data**.")
    st.stop()

# Ensure types after Excel reload
po_db["Purchase Order Date"]   = pd.to_datetime(po_db["Purchase Order Date"], errors="coerce")
po_db["Item Name"]             = po_db["Item Name"].astype(str).str.strip().str.lower()
po_db["Purchase Order Number"] = po_db["Purchase Order Number"].astype(str).str.strip()

b1_db["Bill_Date"]      = pd.to_datetime(b1_db["Bill_Date"], errors="coerce")
b1_db["Invoice_Number"] = b1_db["Invoice_Number"].astype(str).str.strip()
b1_db["PO_Ref"]         = b1_db["PO_Ref"].astype(str).str.strip()

b2_db["Bill_Date"]      = pd.to_datetime(b2_db["Bill_Date"], errors="coerce")
b2_db["Invoice_Number"] = b2_db["Invoice_Number"].astype(str).str.strip()
b2_db["Item_Name_Bill"] = b2_db["Item_Name_Bill"].astype(str).str.strip().str.lower()

# ── JOIN CHAIN ────────────────────────────────────────────────────────────────
# Step 1: Attach PO_Ref to item-level lines via Invoice_Number + Vendor
bills = pd.merge(
    b2_db,
    b1_db[["Invoice_Number", "Vendor Name", "PO_Ref"]],
    on=["Invoice_Number", "Vendor Name"],
    how="left",
)
bills = bills[bills["PO_Ref"].notna() & ~bills["PO_Ref"].isin(["nan", "None", ""])]

# Step 2: Merge enriched lines with PO master on PO_Ref + Item + Vendor
f_df = pd.merge(
    bills,
    po_db,
    left_on=["PO_Ref", "Item_Name_Bill", "Vendor Name"],
    right_on=["Purchase Order Number", "Item Name", "Vendor Name"],
    how="inner",
)

if f_df.empty:
    st.warning("No matching records found. Ensure your files share the same PO numbers and vendor names.")
    st.stop()

# ── CALCULATIONS ──────────────────────────────────────────────────────────────
f_df["Lead_Time"] = (f_df["Bill_Date"] - f_df["Purchase Order Date"]).dt.days
f_df = f_df[f_df["Lead_Time"] >= 0].copy()
f_df["W_Comp"]            = f_df["Lead_Time"] * f_df["Inv_Qty"]
f_df["Item Name Display"] = f_df["Item Name"].str.title()

# Fulfilment: total invoiced qty per PO+item across all invoices
inv_totals = (
    f_df.groupby(["Purchase Order Number", "Item Name"])["Inv_Qty"]
    .sum()
    .reset_index()
    .rename(columns={"Inv_Qty": "Total_Inv_Qty"})
)
f_df = pd.merge(f_df, inv_totals, on=["Purchase Order Number", "Item Name"], how="left")
f_df["Fulfillment_Pct"] = (f_df["Total_Inv_Qty"] / f_df["QuantityOrdered"] * 100).clip(upper=100).round(1)

def get_walt(df: pd.DataFrame) -> float:
    q = df["Inv_Qty"].sum()
    return df["W_Comp"].sum() / q if q > 0 else 0.0

def get_fulfillment_pct(df: pd.DataFrame) -> float:
    """Weighted avg fulfillment % across unique PO+item combinations."""
    unique = df.drop_duplicates(subset=["Purchase Order Number", "Item Name"])
    total_ordered  = unique["QuantityOrdered"].sum()
    total_invoiced = unique["Total_Inv_Qty"].sum()
    return (total_invoiced / total_ordered * 100) if total_ordered > 0 else 0.0


# ── FILTERS ───────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    vendor_choice = st.selectbox("Filter by Vendor", ["All Vendors"] + TARGET_VENDORS)

min_date = f_df["Purchase Order Date"].min().date()
max_date = f_df["Purchase Order Date"].max().date()
with col_f2:
    date_from = st.date_input("PO Date From", value=min_date, min_value=min_date, max_value=max_date)
with col_f3:
    date_to   = st.date_input("PO Date To",   value=max_date, min_value=min_date, max_value=max_date)

# PO number filter — list is scoped to vendor + date selection so only relevant POs show
_pre = f_df.copy()
if vendor_choice != "All Vendors":
    _pre = _pre[_pre["Vendor Name"] == vendor_choice]
_pre = _pre[
    (_pre["Purchase Order Date"].dt.date >= date_from) &
    (_pre["Purchase Order Date"].dt.date <= date_to)
]
available_pos = sorted(_pre["Purchase Order Number"].dropna().unique().tolist())
available_items = sorted(_pre["Item Name Display"].dropna().unique().tolist())

fc1, fc2 = st.columns(2)
with fc1:
    po_filter = st.multiselect(
        "Filter by PO Number",
        options=available_pos,
        default=[],
        placeholder="All POs (select to narrow down…)",
    )
with fc2:
    item_filter = st.multiselect(
        "Filter by Item Name",
        options=available_items,
        default=[],
        placeholder="All items (select to narrow down…)",
    )

view_df = f_df.copy()
if vendor_choice != "All Vendors":
    view_df = view_df[view_df["Vendor Name"] == vendor_choice]
view_df = view_df[
    (view_df["Purchase Order Date"].dt.date >= date_from) &
    (view_df["Purchase Order Date"].dt.date <= date_to)
]
if po_filter:
    view_df = view_df[view_df["Purchase Order Number"].isin(po_filter)]
if item_filter:
    view_df = view_df[view_df["Item Name Display"].isin(item_filter)]

if view_df.empty:
    st.warning("No data for the selected filters.")
    st.stop()


# ── KPIs ──────────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
unique_po_items = view_df.drop_duplicates(subset=["Purchase Order Number", "Item Name"])
m1.metric("Total Order Value",      f"₹{unique_po_items['Item Total'].sum():,.0f}")
m2.metric("Total POs",              view_df["Purchase Order Number"].nunique())
m3.metric("Total SKUs",             view_df["Item Name"].nunique())
m4.metric("Weighted Avg Lead Time", f"{get_walt(view_df):.1f} days")
m5.metric("Avg Fulfillment",        f"{get_fulfillment_pct(view_df):.1f}%")

st.divider()


# ── CHARTS ────────────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

with c1:
    po_group = (
        view_df.groupby("Purchase Order Number")
        .apply(get_walt)
        .reset_index(name="Weighted Lead Time (days)")
    )
    fig1 = px.bar(
        po_group, x="Purchase Order Number", y="Weighted Lead Time (days)",
        title="Weighted Lead Time per PO",
        color="Weighted Lead Time (days)", color_continuous_scale="RdYlGn_r",
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
        item_group, x="Weighted Lead Time (days)", y="Item Name Display",
        orientation="h", title="Lead Time Efficiency by Item",
        color="Weighted Lead Time (days)", color_continuous_scale="RdYlGn_r",
    )
    st.plotly_chart(fig2, use_container_width=True)

if vendor_choice == "All Vendors":
    st.subheader("Vendor Comparison")
    vc1, vc2 = st.columns(2)
    with vc1:
        vendor_group = (
            view_df.groupby("Vendor Name")
            .apply(get_walt)
            .reset_index(name="Weighted Lead Time (days)")
        )
        fig3 = px.bar(
            vendor_group, x="Vendor Name", y="Weighted Lead Time (days)",
            title="Weighted Lead Time by Vendor", color="Vendor Name",
        )
        st.plotly_chart(fig3, use_container_width=True)
    with vc2:
        vf_group = (
            view_df.drop_duplicates(subset=["Purchase Order Number", "Item Name", "Vendor Name"])
            .groupby("Vendor Name")
            .apply(lambda d: (d["Total_Inv_Qty"].sum() / d["QuantityOrdered"].sum() * 100)
                             if d["QuantityOrdered"].sum() > 0 else 0)
            .reset_index(name="Fulfillment %")
        )
        fig_vf = px.bar(
            vf_group, x="Vendor Name", y="Fulfillment %",
            title="Fulfillment % by Vendor", color="Vendor Name",
            range_y=[0, 110],
        )
        fig_vf.add_hline(y=100, line_dash="dash", line_color="green", opacity=0.6)
        st.plotly_chart(fig_vf, use_container_width=True)

st.subheader("📦 Fulfilment by PO")
fc1, fc2 = st.columns(2)

with fc1:
    po_ful = (
        view_df.drop_duplicates(subset=["Purchase Order Number", "Item Name"])
        .groupby("Purchase Order Number")
        .apply(lambda d: (d["Total_Inv_Qty"].sum() / d["QuantityOrdered"].sum() * 100)
                         if d["QuantityOrdered"].sum() > 0 else 0)
        .reset_index(name="Fulfillment %")
        .sort_values("Fulfillment %")
    )
    fig_pof = px.bar(
        po_ful, x="Fulfillment %", y="Purchase Order Number",
        orientation="h", title="Fulfillment % per PO",
        color="Fulfillment %", color_continuous_scale="RdYlGn",
        range_x=[0, 110],
    )
    fig_pof.add_vline(x=100, line_dash="dash", line_color="green", opacity=0.6)
    st.plotly_chart(fig_pof, use_container_width=True)

with fc2:
    item_ful = (
        view_df.drop_duplicates(subset=["Purchase Order Number", "Item Name"])
        .groupby("Item Name Display")
        .apply(lambda d: (d["Total_Inv_Qty"].sum() / d["QuantityOrdered"].sum() * 100)
                         if d["QuantityOrdered"].sum() > 0 else 0)
        .reset_index(name="Fulfillment %")
        .sort_values("Fulfillment %")
    )
    fig_itf = px.bar(
        item_ful, x="Fulfillment %", y="Item Name Display",
        orientation="h", title="Fulfillment % by Item",
        color="Fulfillment %", color_continuous_scale="RdYlGn",
        range_x=[0, 110],
    )
    fig_itf.add_vline(x=100, line_dash="dash", line_color="green", opacity=0.6)
    st.plotly_chart(fig_itf, use_container_width=True)


# ── FULFILLMENT TABLE ─────────────────────────────────────────────────────────
st.subheader("📋 Fulfillment Record")

display_cols = {
    "Purchase Order Number": "PO Number",
    "Invoice_Number":        "Invoice Number",
    "Purchase Order Date":   "PO Date",
    "Vendor Name":           "Vendor",
    "Item Name Display":     "Item",
    "QuantityOrdered":       "PO Qty",
    "Total_Inv_Qty":         "Total Invoiced Qty",
    "Inv_Qty":               "This Invoice Qty",
    "Fulfillment_Pct":       "Fulfillment %",
    "Item Total":            "PO Value (₹)",
    "Bill_Date":             "Bill Date",
    "Lead_Time":             "Lead Time (days)",
}

table_df = view_df[list(display_cols.keys())].rename(columns=display_cols).copy()
table_df["PO Date"]   = table_df["PO Date"].dt.strftime("%d-%b-%Y")
table_df["Bill Date"] = table_df["Bill Date"].dt.strftime("%d-%b-%Y")
table_df["PO Value (₹)"] = table_df["PO Value (₹)"].apply(
    lambda x: f"₹{x:,.0f}" if pd.notna(x) else "-"
)
table_df["Fulfillment %"] = table_df["Fulfillment %"].apply(
    lambda x: f"{x:.1f}%" if pd.notna(x) else "-"
)

st.dataframe(
    table_df,
    use_container_width=True,
    column_config={
        "Fulfillment %": st.column_config.TextColumn("Fulfillment %"),
        "PO Qty":          st.column_config.NumberColumn("PO Qty",          format="%d"),
        "Total Invoiced Qty": st.column_config.NumberColumn("Total Invoiced Qty", format="%.1f"),
        "This Invoice Qty":   st.column_config.NumberColumn("This Invoice Qty",   format="%.1f"),
        "Lead Time (days)":   st.column_config.NumberColumn("Lead Time (days)",   format="%d"),
    },
)

csv_bytes = table_df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Download Fulfillment Report (CSV)",
    data=csv_bytes, file_name="fulfillment_report.csv", mime="text/csv",
)


# ── REMOVE PO DATA ────────────────────────────────────────────────────────────
st.divider()
st.subheader("🗑️ Remove PO Data")
st.caption("Select one or more POs to permanently delete all their records from the database.")

all_pos = sorted(f_df["Purchase Order Number"].dropna().unique().tolist())
pos_to_remove = st.multiselect("Select PO(s) to remove", options=all_pos, placeholder="Choose PO numbers…")

if pos_to_remove:
    affected = f_df[f_df["Purchase Order Number"].isin(pos_to_remove)]
    st.warning(
        f"This will remove **{len(affected)} record(s)** across "
        f"**{affected['Item Name Display'].nunique()} SKU(s)** "
        f"for: {', '.join(pos_to_remove)}"
    )
    if st.button("⚠️ Confirm Removal", type="primary"):
        po_db_new = po_db[~po_db["Purchase Order Number"].isin(pos_to_remove)].copy()
        b1_db_new = b1_db[~b1_db["PO_Ref"].isin(pos_to_remove)].copy()
        invoices_to_drop = b1_db[b1_db["PO_Ref"].isin(pos_to_remove)]["Invoice_Number"].unique()
        b2_db_new = b2_db[~b2_db["Invoice_Number"].isin(invoices_to_drop)].copy()

        with pd.ExcelWriter(DB_FILE, engine="openpyxl") as writer:
            po_db_new.to_excel(writer, sheet_name="POs",          index=False)
            b1_db_new.to_excel(writer, sheet_name="Bills_Header", index=False)
            b2_db_new.to_excel(writer, sheet_name="Bills_Lines",  index=False)

        st.success(f"✅ Removed data for: {', '.join(pos_to_remove)}")
        st.rerun()


# ── RESET ─────────────────────────────────────────────────────────────────────
st.sidebar.divider()
if st.sidebar.button("🗑️ Reset All Data"):
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    st.rerun()
