import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Weighted Lead Time Tracker", layout="wide")

DB_FILE      = "vendor_analytics_db.xlsx"
VENDORS_FILE = "tracked_vendors.txt"
DEFAULT_VENDORS = ["Candor Foods Pvt Ltd.", "Evergreen Foods and Snacks Pvt Ltd"]


# ── HELPERS ────────────────────────────────────────────────────────────────────

def clean_currency(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(r"[₹,\s]", "", regex=True)
        .pipe(pd.to_numeric, errors="coerce")
    )


def load_tracked_vendors() -> list:
    if os.path.exists(VENDORS_FILE):
        try:
            vendors = [v.strip() for v in open(VENDORS_FILE).read().splitlines() if v.strip()]
            if vendors:
                return vendors
        except Exception:
            pass
    return list(DEFAULT_VENDORS)


def save_tracked_vendors(vendors: list):
    with open(VENDORS_FILE, "w") as fh:
        fh.write("\n".join(v.strip() for v in vendors if v.strip()))


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
TARGET_VENDORS = load_tracked_vendors()


# ── SIDEBAR ────────────────────────────────────────────────────────────────────

with st.sidebar.expander("⚙️ Vendor Settings", expanded=False):
    st.caption("Add or remove vendors to track. Only these vendors are imported from uploaded files.")
    new_vendor_input = st.text_input(
        "Add a new vendor (exact name as in files)",
        placeholder="e.g. ABC Suppliers Pvt Ltd.",
        key="new_vendor_input",
    )
    if st.button("➕ Add Vendor", key="add_vendor_btn"):
        nv = new_vendor_input.strip()
        if nv and nv not in TARGET_VENDORS:
            TARGET_VENDORS.append(nv)
            save_tracked_vendors(TARGET_VENDORS)
            st.success(f"Added: {nv}")
            st.rerun()
        elif nv in TARGET_VENDORS:
            st.warning("Already tracked.")
    st.markdown("**Currently tracked:**")
    vendors_to_keep = []
    for v in TARGET_VENDORS:
        if st.checkbox(v, value=True, key=f"vchk_{v}"):
            vendors_to_keep.append(v)
    if st.button("💾 Save Vendor List", key="save_vendors_btn"):
        if not vendors_to_keep:
            st.error("At least one vendor must remain.")
        else:
            save_tracked_vendors(vendors_to_keep)
            st.rerun()

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
        # Collapse duplicates within the uploaded file on natural key
        df_po = df_po.drop_duplicates(subset=["Purchase Order Number", "Item Name"], keep="last")
        if not po_db.empty:
            existing_keys_po = set(zip(
                po_db["Purchase Order Number"].astype(str),
                po_db["Item Name"].astype(str),
            ))
            mask_new_po = ~df_po.apply(
                lambda r: (str(r["Purchase Order Number"]), str(r["Item Name"])) in existing_keys_po, axis=1
            )
            po_db = pd.concat([po_db, df_po[mask_new_po]], ignore_index=True)
        else:
            po_db = df_po

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
                # Drop rows with no item name — they cannot be matched to a PO line
                b2 = b2[b2["Item_Name_Bill"].notna() & (b2["Item_Name_Bill"] != "nan") & (b2["Item_Name_Bill"] != "")]
                new_b2_list.append(b2)

    # ── Upsert: new rows only, existing DB records are never dropped ────────
    #
    # Natural keys (decide uniqueness):
    #   PO master        →  Purchase Order Number  +  Item Name
    #   Bills_Header(b1) →  Invoice_Number         +  Vendor Name
    #   Bills_Lines (b2) →  Invoice_Number         +  Vendor Name  +  Item_Name_Bill
    #
    # Rules:
    #   1. Collapse any within-file duplicates on the natural key (keep last).
    #   2. Compare incoming rows against the existing DB on the natural key.
    #   3. Rows whose key already exists in the DB are SKIPPED — existing wins.
    #   4. Only genuinely new rows are appended to the DB.
    #   5. Existing DB rows that are NOT in the upload are KEPT untouched.

    def upsert(existing: pd.DataFrame, incoming: pd.DataFrame, key_cols: list):
        """Append rows from incoming that don't already exist in DB by natural key."""
        # Step 1 — within-upload dedup
        incoming = incoming.drop_duplicates(subset=key_cols, keep="last")
        if existing.empty:
            return incoming, len(incoming), 0
        # Step 2 — build existing key set (use fillna to handle NaN safely)
        existing_keys = set(
            zip(*[existing[c].astype(str).fillna("__null__") for c in key_cols])
        )
        # Step 3 — flag new vs duplicate
        is_dupe = incoming.apply(
            lambda r: tuple(str(r[c]) if pd.notna(r[c]) else "__null__" for c in key_cols)
                      in existing_keys,
            axis=1,
        )
        new_rows = incoming[~is_dupe]
        n_dupes  = int(is_dupe.sum())
        # Step 4 — append only new rows; existing DB is preserved in full
        merged = pd.concat([existing, new_rows], ignore_index=True)
        return merged, len(new_rows), n_dupes

    msgs = []

    if new_b1_list:
        incoming_b1 = pd.concat(new_b1_list, ignore_index=True)
        b1_db, added, skipped = upsert(b1_db, incoming_b1, ["Invoice_Number", "Vendor Name"])
        if skipped > 0 and added == 0:
            msgs.append(f"📋 Bills Header: all {skipped} row(s) already in DB — nothing added.")
        elif skipped > 0:
            msgs.append(f"📋 Bills Header: **{added}** new row(s) added, **{skipped}** already existed (skipped).")
        else:
            msgs.append(f"📋 Bills Header: **{added}** new row(s) added.")

    if new_b2_list:
        incoming_b2 = pd.concat(new_b2_list, ignore_index=True)
        b2_db, added, skipped = upsert(b2_db, incoming_b2, ["Invoice_Number", "Vendor Name", "Item_Name_Bill"])
        if skipped > 0 and added == 0:
            msgs.append(f"🧾 Bills Lines: all {skipped} row(s) already in DB — nothing added.")
        elif skipped > 0:
            msgs.append(f"🧾 Bills Lines: **{added}** new row(s) added, **{skipped}** already existed (skipped).")
        else:
            msgs.append(f"🧾 Bills Lines: **{added}** new row(s) added.")

    if po_file:
        incoming_po = po_db if po_db.empty else po_db  # po_db already set above
        # Re-load the original parsed df_po and upsert against the pre-existing DB
        # po_db was already replaced in the po_file block above — reload DB snapshot
        po_db_snap, _, _ = load_db()
        po_db_existing = po_db_snap if not po_db_snap.empty else pd.DataFrame()
        # incoming_po is whatever was just parsed from the file
        # We need to redo the merge properly: use the parsed df_po vs pre-upload po_db
        # Since po_db was already overwritten above, use it as incoming and po_db_snap as base
        if not po_db_existing.empty:
            po_db_existing["Item Name"]             = po_db_existing["Item Name"].astype(str).str.strip().str.lower()
            po_db_existing["Purchase Order Number"] = po_db_existing["Purchase Order Number"].astype(str).str.strip()
            po_db, added_po, skipped_po = upsert(po_db_existing, po_db, ["Purchase Order Number", "Item Name"])
            if skipped_po > 0 and added_po == 0:
                msgs.append(f"📦 POs: all {skipped_po} row(s) already in DB — nothing added.")
            elif skipped_po > 0:
                msgs.append(f"📦 POs: **{added_po}** new row(s) added, **{skipped_po}** already existed (skipped).")
            else:
                msgs.append(f"📦 POs: **{added_po}** new row(s) added.")
        else:
            msgs.append(f"📦 POs: **{len(po_db)}** row(s) loaded (first import).")

    if not po_db.empty and not b1_db.empty and not b2_db.empty:
        with pd.ExcelWriter(DB_FILE, engine="openpyxl") as writer:
            po_db.to_excel(writer, sheet_name="POs",          index=False)
            b1_db.to_excel(writer, sheet_name="Bills_Header", index=False)
            b2_db.to_excel(writer, sheet_name="Bills_Lines",  index=False)
        st.sidebar.success("✅ Database updated!")
        for m in msgs:
            st.sidebar.info(m)
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

inv_totals = (
    f_df.groupby(["Purchase Order Number", "Item Name"])["Inv_Qty"]
    .sum().reset_index().rename(columns={"Inv_Qty": "Total_Inv_Qty"})
)
f_df = pd.merge(f_df, inv_totals, on=["Purchase Order Number", "Item Name"], how="left")
f_df["Fulfillment_Pct"] = (f_df["Total_Inv_Qty"] / f_df["QuantityOrdered"] * 100).clip(upper=100).round(1)
f_df["Supply_Status"]   = f_df["Fulfillment_Pct"].apply(
    lambda x: "🟡 Partially Supplied" if x < 100 else "🟢 Fully Supplied"
)

# ── UNINVOICED PO ROWS ────────────────────────────────────────────────────────
matched_keys = set(zip(f_df["Purchase Order Number"], f_df["Item Name"]))
unmatched_po = po_db[
    ~po_db.apply(lambda r: (r["Purchase Order Number"], r["Item Name"]) in matched_keys, axis=1)
].copy()
unmatched_po["Item Name Display"] = unmatched_po["Item Name"].str.title()
unmatched_po["Invoice_Number"]    = "—"
unmatched_po["Inv_Qty"]           = 0.0
unmatched_po["Total_Inv_Qty"]     = 0.0
unmatched_po["Fulfillment_Pct"]   = 0.0
unmatched_po["Lead_Time"]         = pd.NA
unmatched_po["W_Comp"]            = pd.NA
unmatched_po["Bill_Date"]         = pd.NaT
unmatched_po["Supply_Status"]     = "🔴 Yet to be Supplied"

# all_df = invoiced + uninvoiced (fulfillment charts, table, Remove PO list)
# lt_df  = invoiced only          (lead-time charts & WALT KPI)
all_df = pd.concat([f_df, unmatched_po], ignore_index=True)


def get_walt(df: pd.DataFrame) -> float:
    q = df["Inv_Qty"].sum()
    return df["W_Comp"].sum() / q if q > 0 else 0.0

def get_fulfillment_pct(df: pd.DataFrame) -> float:
    unique = df.drop_duplicates(subset=["Purchase Order Number", "Item Name"])
    total_ordered  = unique["QuantityOrdered"].sum()
    total_invoiced = unique["Total_Inv_Qty"].fillna(0).sum()
    return (total_invoiced / total_ordered * 100) if total_ordered > 0 else 0.0


# ── FILTERS ───────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    vendor_choice = st.selectbox("Filter by Vendor", ["All Vendors"] + TARGET_VENDORS)

min_date = all_df["Purchase Order Date"].min().date()
max_date = all_df["Purchase Order Date"].max().date()
with col_f2:
    date_from = st.date_input("PO Date From", value=min_date, min_value=min_date, max_value=max_date)
with col_f3:
    date_to   = st.date_input("PO Date To",   value=max_date, min_value=min_date, max_value=max_date)

_pre = all_df.copy()
if vendor_choice != "All Vendors":
    _pre = _pre[_pre["Vendor Name"] == vendor_choice]
_pre = _pre[
    (_pre["Purchase Order Date"].dt.date >= date_from) &
    (_pre["Purchase Order Date"].dt.date <= date_to)
]
available_pos   = sorted(_pre["Purchase Order Number"].dropna().unique().tolist())
available_items = sorted(_pre["Item Name Display"].dropna().unique().tolist())

fc1, fc2 = st.columns(2)
with fc1:
    po_filter = st.multiselect("Filter by PO Number", options=available_pos, default=[],
                               placeholder="All POs (select to narrow down…)")
with fc2:
    item_filter = st.multiselect("Filter by Item Name", options=available_items, default=[],
                                 placeholder="All items (select to narrow down…)")

view_df = all_df.copy()
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

lt_df = view_df[view_df["Inv_Qty"] > 0].copy()


# ── KPIs ──────────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5, m6 = st.columns(6)
unique_po_items = view_df.drop_duplicates(subset=["Purchase Order Number", "Item Name"])
uninvoiced_pos  = view_df[view_df["Inv_Qty"] == 0]["Purchase Order Number"].nunique()
m1.metric("Total Order Value",      f"₹{unique_po_items['Item Total'].sum():,.0f}")
m2.metric("Total POs",              view_df["Purchase Order Number"].nunique())
m3.metric("Yet to be Supplied",     uninvoiced_pos,
          delta=f"-{uninvoiced_pos} pending" if uninvoiced_pos > 0 else None,
          delta_color="inverse")
m4.metric("Total SKUs",             view_df["Item Name"].nunique())
m5.metric("Weighted Avg Lead Time", f"{get_walt(lt_df):.1f} days" if not lt_df.empty else "N/A")
m6.metric("Avg Fulfillment",        f"{get_fulfillment_pct(view_df):.1f}%")

st.divider()


# ── CHARTS ────────────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

with c1:
    if not lt_df.empty:
        po_group = (
            lt_df.groupby("Purchase Order Number")
            .apply(get_walt)
            .reset_index(name="Weighted Lead Time (days)")
        )
        fig1 = px.bar(
            po_group, x="Purchase Order Number", y="Weighted Lead Time (days)",
            title="Weighted Lead Time per PO (invoiced only)",
            color="Weighted Lead Time (days)", color_continuous_scale="RdYlGn_r",
        )
        fig1.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig1, use_container_width=True)
    else:
        st.info("No invoiced POs in selection.")

with c2:
    if not lt_df.empty:
        item_group = (
            lt_df.groupby("Item Name Display")
            .apply(get_walt)
            .reset_index(name="Weighted Lead Time (days)")
            .sort_values("Weighted Lead Time (days)", ascending=True)
        )
        fig2 = px.bar(
            item_group, x="Weighted Lead Time (days)", y="Item Name Display",
            orientation="h", title="Lead Time Efficiency by Item (invoiced only)",
            color="Weighted Lead Time (days)", color_continuous_scale="RdYlGn_r",
        )
        st.plotly_chart(fig2, use_container_width=True)

if vendor_choice == "All Vendors":
    st.subheader("Vendor Comparison")
    vc1, vc2 = st.columns(2)
    with vc1:
        vendor_group = (
            lt_df.groupby("Vendor Name")
            .apply(get_walt)
            .reset_index(name="Weighted Lead Time (days)")
        )
        fig3 = px.bar(
            vendor_group, x="Vendor Name", y="Weighted Lead Time (days)",
            title="Weighted Lead Time by Vendor (invoiced only)", color="Vendor Name",
        )
        st.plotly_chart(fig3, use_container_width=True)
    with vc2:
        vf_group = (
            view_df.drop_duplicates(subset=["Purchase Order Number", "Item Name", "Vendor Name"])
            .groupby("Vendor Name")
            .apply(lambda d: (d["Total_Inv_Qty"].fillna(0).sum() / d["QuantityOrdered"].sum() * 100)
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
        .apply(lambda d: (d["Total_Inv_Qty"].fillna(0).sum() / d["QuantityOrdered"].sum() * 100)
                         if d["QuantityOrdered"].sum() > 0 else 0)
        .reset_index(name="Fulfillment %")
        .sort_values("Fulfillment %")
    )
    fig_pof = px.bar(
        po_ful, x="Fulfillment %", y="Purchase Order Number",
        orientation="h", title="Fulfillment % per PO (0% = yet to supply)",
        color="Fulfillment %", color_continuous_scale="RdYlGn",
        range_x=[0, 110],
    )
    fig_pof.add_vline(x=100, line_dash="dash", line_color="green", opacity=0.6)
    st.plotly_chart(fig_pof, use_container_width=True)

with fc2:
    item_ful = (
        view_df.drop_duplicates(subset=["Purchase Order Number", "Item Name"])
        .groupby("Item Name Display")
        .apply(lambda d: (d["Total_Inv_Qty"].fillna(0).sum() / d["QuantityOrdered"].sum() * 100)
                         if d["QuantityOrdered"].sum() > 0 else 0)
        .reset_index(name="Fulfillment %")
        .sort_values("Fulfillment %")
    )
    fig_itf = px.bar(
        item_ful, x="Fulfillment %", y="Item Name Display",
        orientation="h", title="Fulfillment % by Item (includes pending)",
        color="Fulfillment %", color_continuous_scale="RdYlGn",
        range_x=[0, 110],
    )
    fig_itf.add_vline(x=100, line_dash="dash", line_color="green", opacity=0.6)
    st.plotly_chart(fig_itf, use_container_width=True)


# ── FULFILLMENT TABLE ─────────────────────────────────────────────────────────
st.subheader("📋 Fulfillment Record")

display_cols = {
    "Supply_Status":         "Status",
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
table_df["Bill Date"] = table_df["Bill Date"].apply(
    lambda x: x.strftime("%d-%b-%Y") if pd.notna(x) else "—"
)
table_df["PO Value (₹)"] = table_df["PO Value (₹)"].apply(
    lambda x: f"₹{x:,.0f}" if pd.notna(x) else "-"
)
table_df["Fulfillment %"] = table_df["Fulfillment %"].apply(
    lambda x: f"{x:.1f}%" if pd.notna(x) else "0.0%"
)
table_df["This Invoice Qty"] = table_df["This Invoice Qty"].apply(
    lambda x: x if pd.notna(x) and x > 0 else "—"
)
table_df["Lead Time (days)"] = table_df["Lead Time (days)"].apply(
    lambda x: int(x) if pd.notna(x) else "—"
)
table_df = table_df.sort_values(["Status", "PO Number"], ascending=[True, True])

st.dataframe(
    table_df,
    use_container_width=True,
    column_config={
        "Status":             st.column_config.TextColumn("Status", width="medium"),
        "Fulfillment %":      st.column_config.TextColumn("Fulfillment %"),
        "PO Qty":             st.column_config.NumberColumn("PO Qty", format="%d"),
        "Total Invoiced Qty": st.column_config.NumberColumn("Total Invoiced Qty", format="%.1f"),
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

all_pos = sorted(all_df["Purchase Order Number"].dropna().unique().tolist())
pos_to_remove = st.multiselect("Select PO(s) to remove", options=all_pos, placeholder="Choose PO numbers…")

if pos_to_remove:
    affected = all_df[all_df["Purchase Order Number"].isin(pos_to_remove)]
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
col_r1, col_r2 = st.sidebar.columns(2)
with col_r1:
    if st.sidebar.button("🗑️ Reset Data", key="reset_data"):
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        st.rerun()
with col_r2:
    if st.sidebar.button("↩️ Reset Vendors", key="reset_vendors"):
        if os.path.exists(VENDORS_FILE):
            os.remove(VENDORS_FILE)
        st.rerun()
