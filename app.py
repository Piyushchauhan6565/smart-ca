
import sqlite3
import os
import re
import json
import urllib.request
import urllib.error
from pathlib import Path

import pandas as pd
import streamlit as st

from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as PDFImage,
)
from xml.sax.saxutils import escape

st.set_page_config(
    page_title="SMART CA",
    page_icon="📊",
    layout="wide",
)

# Database is stored in your project folder
DB_PATH = Path(__file__).parent / "smart_ca.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def validate_gstin_format(gstin):
    """Basic GSTIN structure check. This is not proof of registration status."""
    value = str(gstin or "").strip().upper()
    pattern = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
    if not re.fullmatch(pattern, value):
        return False, "GSTIN must be 15 characters and follow the standard GSTIN format."
    if value[:2] == "00":
        return False, "The first two GSTIN characters must be a valid state/UT code, not 00."
    return True, "Format looks correct; registration still needs provider/official verification."


def fetch_gstin_profile(gstin):
    """Fetch buyer details using the configured GSTINAPI.in API key."""
    gstin = str(gstin or "").strip().upper()
    valid, validation_message = validate_gstin_format(gstin)
    if not valid:
        return None, validation_message

    api_key = os.getenv("SMART_CA_GST_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = str(st.secrets.get("SMART_CA_GST_API_KEY", "")).strip()
        except Exception:
            api_key = ""
    if not api_key:
        return None, (
            "GST lookup is not configured. Add SMART_CA_GST_API_KEY to "
            ".streamlit/secrets.toml, then restart SMART CA. Never share the key in chat or GitHub."
        )

    url = "https://gstin.cloud/api/v1/verify/" + gstin
    request = urllib.request.Request(
    url,
    headers={
        "X-API-Key": api_key,
        "Accept": "application/json"
    },
    method="GET"
)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        messages = {
            401: "GST provider rejected the API key (HTTP 401). Check the key in your provider dashboard.",
            402: "GST provider reports that no API credits remain (HTTP 402). Check your provider dashboard.",
            403: "GST provider denied access (HTTP 403). Check API permissions or contact provider support.",
            422: "GST provider rejected this GSTIN (HTTP 422). Recheck it on the official GST portal.",
            429: "GST provider rate limit reached. Wait briefly and try again.",
        }
        return None, messages.get(exc.code, f"GST provider returned HTTP {exc.code}. Try again or check its dashboard.")
    except urllib.error.URLError:
        return None, "Could not connect to the GST provider. Check internet access and try again."
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None, "The GST provider timed out or returned unreadable data. Please try again."

        
    if not isinstance(payload, dict):
        return None, "GST provider returned an unexpected response format."

    # Never autofill buyer details from an explicit sandbox response.
    if payload.get("sandbox") is True:
        return None, (
            "The provider returned sandbox/demo data. "
            "No buyer details were autofilled. "
            "Use the provider's live production API for real invoices."
        )

    if payload.get("success") is False:
        return None, str(
            payload.get("error")
            or "GST provider could not verify this GSTIN."
        )

    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None, "GST provider returned an unexpected taxpayer record."

        return None, str(
            payload.get("error")
            or "GST provider could not verify this GSTIN."
        )

    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None, "GST provider returned an unexpected taxpayer record."

    def first_value(source, *keys):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
        return ""

    returned_gstin = str(first_value(data, "gstin", "GSTIN") or gstin).strip().upper()
    if returned_gstin != gstin:
        return None, "The provider returned a different GSTIN. No buyer details were filled."

    legal_name = first_value(data, "legal_name", "lgnm", "legalName", "registered_name", "name")
    trade_name = first_value(data, "trade_name", "tradeNam", "tradeName", "trade_name_as_per_gst")
    address = first_value(data, "principal_address", "address", "pradr", "principalAddress", "registered_address")
    state = first_value(data, "state_name", "state", "stateName", "stcd")
    status = str(first_value(data, "registration_status", "status", "sts", "registrationStatus") or "").strip()

    if isinstance(address, dict):
        # Support both GST-style nested principal address and flattened address fields.
        nested = address.get("addr") if isinstance(address.get("addr"), dict) else address
        parts = [first_value(nested, key) for key in
                 ("bno", "flno", "bnm", "building_name", "st", "street", "loc", "locality", "dst", "district", "city", "stcd", "state", "pncd", "pincode")]
        address = ", ".join(str(part).strip() for part in parts if str(part or "").strip())
    elif isinstance(address, list):
        address = ", ".join(str(x).strip() for x in address if str(x or "").strip())
    else:
        address = str(address or "").strip()

    if isinstance(state, dict):
        state = first_value(state, "name", "state_name", "code")
    state = str(state or "").strip()
    if not state and isinstance(data.get("pradr"), dict):
        addr = data["pradr"].get("addr", data["pradr"])
        if isinstance(addr, dict):
            state = str(first_value(addr, "state", "stcd") or "").strip()

    legal_name = str(legal_name or "").strip()
    trade_name = str(trade_name or "").strip()
    # Refuse obvious demo/sandbox records: they must never populate a real invoice.
    record_text = " ".join((legal_name, trade_name, str(address or ""), str(status or ""))).lower()
    demo_markers = ("sandbox", "test business", "test trade name", "dummy", "sample taxpayer", "example company")
    if any(marker in record_text for marker in demo_markers):
        return None, (
            "The GST provider returned an obvious test/demo record, not trustworthy buyer details. "
            "No customer fields were autofilled. Check that your provider account and endpoint are "
            "configured for live production lookups, and verify this GSTIN on the official GST Portal."
        )

    # Use trade name for invoice customer name when present, otherwise legal name.
    display_name = trade_name or legal_name
    if not display_name and not address:
        return None, "The provider response contained no usable business name or address. Check the provider response."

    normalized_status = status.lower().strip()
    if normalized_status in {"active", "act", "active registration"}:
        status_label = "Active (provider-reported; verify before issuing invoice)"
        status_kind = "active"
    elif normalized_status in {"cancelled", "canceled", "inactive", "suspended", "cancel", "suspend"}:
        status_label = f"{status} (provider-reported; do not treat as active)"
        status_kind = "inactive"
    elif status:
        status_label = f"{status} (provider-reported; verify on official portal)"
        status_kind = "unknown"
    else:
        status_label = "Not provided by API — verify on official GST portal"
        status_kind = "unknown"

    return {
        "gstin": returned_gstin,
        "name": display_name,
        "legal_name": legal_name,
        "trade_name": trade_name,
        "address": address,
        "state": state,
        "status": status_label,
        "status_kind": status_kind,
    }, None


def setup_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT UNIQUE NOT NULL,
                hsn_code TEXT DEFAULT '',
                quantity INTEGER NOT NULL DEFAULT 0,
                price REAL NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        columns = [
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(products)"
            ).fetchall()
        ]

        if "hsn_code" not in columns:
            conn.execute(
                "ALTER TABLE products ADD COLUMN hsn_code TEXT DEFAULT ''"
            )


        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                subtotal REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS business_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                business_name TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                gstin TEXT NOT NULL DEFAULT '',
                logo_path TEXT NOT NULL DEFAULT ''
            )
        """)

        # Store multiple products under one invoice
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                product_id INTEGER,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                subtotal REAL NOT NULL,
                FOREIGN KEY (invoice_id) REFERENCES invoices(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)

        # Preserve existing invoices by copying their current item
        # into the new table, without duplicating migrated items.
        conn.execute("""
            INSERT INTO invoice_items (
                invoice_id, product_id, product_name,
                quantity, unit_price, subtotal
            )
            SELECT
                i.id, i.product_id, i.product_name,
                i.quantity, i.unit_price, i.subtotal
            FROM invoices AS i
            WHERE NOT EXISTS (
                SELECT 1
                FROM invoice_items AS ii
                WHERE ii.invoice_id = i.id
            )
        """)

        conn.execute("""
            INSERT OR IGNORE INTO business_profile (id)
            VALUES (1)
        """)

        # Safely add customer contact fields to existing invoice databases
        invoice_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(invoices)"
            ).fetchall()
        }
        if "customer_address" not in invoice_columns:
            conn.execute("""
                ALTER TABLE invoices
                ADD COLUMN customer_address TEXT NOT NULL DEFAULT ''
            """)
        if "customer_phone" not in invoice_columns:
            conn.execute("""
                ALTER TABLE invoices
                ADD COLUMN customer_phone TEXT NOT NULL DEFAULT ''
            """)
        if "buyer_registered" not in invoice_columns:
            conn.execute("""
                ALTER TABLE invoices
                ADD COLUMN buyer_registered TEXT NOT NULL DEFAULT 'Unknown'
            """)
        if "buyer_gstin" not in invoice_columns:
            conn.execute("""
                ALTER TABLE invoices
                ADD COLUMN buyer_gstin TEXT NOT NULL DEFAULT ''
            """)

        # GST migration: add fields without deleting existing records.
        def add_column_if_missing(table_name, column_name, definition):
            columns = {
                row[1] for row in conn.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            if column_name not in columns:
                conn.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                )

        add_column_if_missing("products", "gst_rate", "REAL NOT NULL DEFAULT 18")
        for column, definition in [
            ("gst_rate", "REAL NOT NULL DEFAULT 0"),
            ("taxable_value", "REAL NOT NULL DEFAULT 0"),
            ("cgst_amount", "REAL NOT NULL DEFAULT 0"),
            ("sgst_amount", "REAL NOT NULL DEFAULT 0"),
            ("igst_amount", "REAL NOT NULL DEFAULT 0"),
            ("total_amount", "REAL NOT NULL DEFAULT 0"),
        ]:
            add_column_if_missing("invoice_items", column, definition)

        for column, definition in [
            ("supply_type", "TEXT NOT NULL DEFAULT ''"),
            ("place_of_supply", "TEXT NOT NULL DEFAULT ''"),
            ("taxable_total", "REAL NOT NULL DEFAULT 0"),
            ("cgst_total", "REAL NOT NULL DEFAULT 0"),
            ("sgst_total", "REAL NOT NULL DEFAULT 0"),
            ("igst_total", "REAL NOT NULL DEFAULT 0"),
            ("grand_total", "REAL NOT NULL DEFAULT 0"),
        ]:
            add_column_if_missing("invoices", column, definition)

        count = conn.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

        # Add fictional sample products only to an empty inventory
        if count == 0:
            sample_products = [
                ("Notebook", "DEMO001", 25, 50.00),
                ("Ball Pen", "DEMO002", 100, 10.00),
                ("USB Cable", "DEMO003", 15, 149.00),
            ]
            conn.executemany("""
                INSERT INTO products (name, sku, quantity, price)
                VALUES (?, ?, ?, ?)
            """, sample_products)


def load_products():
    with get_connection() as conn:
        return pd.read_sql_query("""
            SELECT id, name, sku, quantity, price, gst_rate
            FROM products
            ORDER BY id DESC
        """, conn)


setup_database()
products = load_products()

# Sidebar navigation
st.sidebar.title("📊 SMART CA")
st.sidebar.caption("Smart Business & Accounting Assistant")

section = st.sidebar.radio(
    "MAIN MENU",
    [
        "Dashboard",
        "Business Profile",
        "Inventory",
        "Billing",
        "Party Ledger",
        "Accounting",
        "GST & Tax",
        "AI Assistant",
    ],
)

st.sidebar.divider()
st.sidebar.caption("MVP • Development version")

# Dashboard
if section == "Dashboard":
    st.title("Welcome to SMART CA 👋")
    st.write("Your business overview, all in one place.")
    st.caption("DEMO MODE — inventory contains fictional sample products.")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total Sales", "Rs.0")
    col2.metric("Purchases", "Rs.0")
    col3.metric("Outstanding", "Rs.0")
    col4.metric("Inventory Items", len(products))

    st.divider()
    st.subheader("Current Inventory")

    if not products.empty:
        st.dataframe(
            products[["name", "sku", "quantity", "price", "gst_rate"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No products available.")

    st.caption("Sales, purchases, and outstanding balances are not implemented yet.")

elif section == "Business Profile":
    st.title("🏢 Business Profile")
    st.write("Enter the details that will appear on your invoices.")

    with get_connection() as conn:
        profile = conn.execute("""
            SELECT business_name, address, phone, email, gstin, logo_path
            FROM business_profile
            WHERE id = 1
        """).fetchone()

    with st.form("business_profile_form"):
        business_name = st.text_input(
            "Business Name",
            value=profile[0] or "",
        )
        address = st.text_area(
            "Business Address",
            value=profile[1] or "",
        )
        phone = st.text_input(
            "Phone Number",
            value=profile[2] or "",
        )
        email = st.text_input(
            "Email Address",
            value=profile[3] or "",
        )
        gstin = st.text_input(
            "GSTIN (optional)",
            value=profile[4] or "",
        )
        uploaded_logo = st.file_uploader(
            "Upload Business Logo",
            type=["png", "jpg", "jpeg"],
        )

        save_profile = st.form_submit_button("Save Business Profile")

    if save_profile:
        logo_path = profile[5] or ""

        if uploaded_logo is not None:
            extension = Path(uploaded_logo.name).suffix.lower()
            logo_file = Path(__file__).parent / f"smart_ca_logo{extension}"
            logo_file.write_bytes(uploaded_logo.getvalue())
            logo_path = str(logo_file)

        with get_connection() as conn:
            conn.execute("""
                UPDATE business_profile
                SET business_name = ?,
                    address = ?,
                    phone = ?,
                    email = ?,
                    gstin = ?,
                    logo_path = ?
                WHERE id = 1
            """, (
                business_name.strip(),
                address.strip(),
                phone.strip(),
                email.strip(),
                gstin.strip(),
                logo_path,
            ))

        st.success("Business profile saved successfully!")
        st.rerun()

    if profile[5] and Path(profile[5]).is_file():
        st.subheader("Current Business Logo")
        st.image(profile[5], width=180)

# Inventory
elif section == "Inventory":
    st.title("📦 Inventory Management")
    st.write("Add products and keep track of stock and selling prices.")

    with st.expander("➕ Add a new product", expanded=False):
        with st.form("add_product_form"):
            name = st.text_input("Product name")
            sku = st.text_input("Product code / SKU")
            hsn_code = st.text_input("HSN Code", max_chars=8)
            quantity = st.number_input(
                "Opening stock",
                min_value=0,
                step=1,
            )
            price = st.number_input(
                "Selling price before GST (Rs.)",
                min_value=0.0,
                step=1.0,
                format="%.2f",
            )
            gst_rate = st.selectbox(
                "GST rate for this product",
                options=[0, 5, 12, 18, 28],
                index=3,
                format_func=lambda rate: f"{rate}%",
            )

            submitted = st.form_submit_button("Save Product")

        if submitted:
            if not name.strip() or not sku.strip():
                st.error("Please enter both product name and product code.")
            else:
                try:
                    with get_connection() as conn:
                        
                        conn.execute(
                            """
                            INSERT INTO products
                            (name, sku, hsn_code, quantity, price, gst_rate)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                name.strip(),
                                sku.strip().upper(),
                                hsn_code.strip(),
                                quantity,
                                price,
                                gst_rate,
                            ),
                        )
                    st.success("Product saved successfully!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That product code already exists. Use a unique code.")

    st.subheader(f"Products in Inventory: {len(products)}")

    if not products.empty:
        display_products = products.copy()
        display_products["price"] = display_products["price"].map(
            lambda value: f"Rs.{value:,.2f}"
        )
        display_products["gst_rate"] = display_products["gst_rate"].map(
            lambda value: f"{value:g}%"
        )
        st.dataframe(
            display_products,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "Download inventory as CSV",
            data=products.to_csv(index=False).encode("utf-8"),
            file_name="smart_ca_inventory.csv",
            mime="text/csv",
        )
    else:
        st.info("Your inventory is empty. Add a product above.")

# Other modules — planned


elif section == "Billing":
    st.title("🧾 GST Billing & Invoices")
    st.write("Create a multi-product invoice with GST added to prices.")
    st.caption("GST is calculated using each product's saved rate. Verify the correct rate and tax treatment before issuing a real tax invoice.")

    if products.empty:
        st.warning("Please add products in Inventory before creating an invoice.")
    else:
        available_products = products[products["quantity"] > 0]
        if available_products.empty:
            st.warning("No products are currently in stock.")
        else:
            product_options = {
                f"{row['name']} (Stock: {int(row['quantity'])}) — Rs.{float(row['price']):,.2f} — GST {float(row.get('gst_rate', 18)):g}%": int(row["id"])
                for _, row in available_products.iterrows()
            }

            st.subheader("1. Buyer GST Registration")
            buyer_registration_label = st.radio(
                "Is the buyer GST registered?",
                ["Registered", "Unregistered"],
                horizontal=True,
                key="billing_buyer_registration",
                help="Choose Registered if the buyer has a GSTIN."
            )
            buyer_registered = "Registered" if buyer_registration_label == "Registered" else "Unregistered"
            buyer_gstin = ""
            if buyer_registered == "Registered":
                buyer_gstin = st.text_input(
                    "Buyer GSTIN", key="billing_buyer_gstin", max_chars=15,
                    placeholder="15-character GSTIN"
                ).strip().upper()
                if buyer_gstin:
                    valid_gstin, gstin_message = validate_gstin_format(buyer_gstin)
                    if not valid_gstin:
                        st.warning(gstin_message)
                    else:
                        st.caption("GSTIN format: looks correct. This alone does not confirm registration status.")
                    if st.button("Fetch Buyer Details", key="fetch_buyer_gstin"):
                        if not valid_gstin:
                            st.error(gstin_message)
                        else:
                            profile, lookup_error = fetch_gstin_profile(buyer_gstin)
                            if lookup_error:
                                st.error(lookup_error)
                                st.markdown("Manual verification: [Search Taxpayer on the official GST Portal](https://services.gst.gov.in/services/searchtp). Complete the CAPTCHA and compare the GSTIN, legal name, status, and principal place of business.")
                            else:
                                if profile.get("name"):
                                    st.session_state["billing_customer_name"] = profile["name"]
                                if profile.get("address"):
                                    st.session_state["billing_customer_address"] = profile["address"]
                                if profile.get("state"):
                                    st.session_state["billing_place_of_supply"] = profile["state"]
                                st.session_state["billing_gstin_lookup_status"] = profile.get("status", "")
                                st.session_state["billing_gstin_lookup_legal_name"] = profile.get("legal_name", "")
                                st.session_state["billing_gstin_lookup_trade_name"] = profile.get("trade_name", "")
                                st.session_state["billing_gstin_lookup_status_kind"] = profile.get("status_kind", "unknown")
                                st.session_state["billing_gstin_lookup_checked"] = profile.get("gstin", "")
                                st.rerun()
                if st.session_state.get("billing_gstin_lookup_checked") == buyer_gstin and buyer_gstin:
                    legal = st.session_state.get("billing_gstin_lookup_legal_name", "")
                    trade = st.session_state.get("billing_gstin_lookup_trade_name", "")
                    status_text = st.session_state.get("billing_gstin_lookup_status", "Not provided by API — verify on official GST portal")
                    status_kind = st.session_state.get("billing_gstin_lookup_status_kind", "unknown")
                    if status_kind == "active":
                        st.success("Provider status: " + status_text)
                    elif status_kind == "inactive":
                        st.error("Registration warning: " + status_text)
                    else:
                        st.warning("Registration status: " + status_text)
                    left, right = st.columns(2)
                    with left:
                        st.text_input("Legal Name (provider result)", value=legal or "Not returned by provider", disabled=True, key="billing_gstin_legal_display")
                    with right:
                        st.text_input("Trade Name (provider result)", value=trade or "Not returned by provider", disabled=True, key="billing_gstin_trade_display")
                    st.caption("Autofilled information is a convenience, not a substitute for checking the official GST portal. Confirm details before issuing a tax invoice.")
            else:
                st.session_state["billing_buyer_gstin"] = ""
                st.session_state["billing_gstin_lookup_status"] = ""
                st.session_state["billing_gstin_lookup_checked"] = ""
                st.session_state["billing_gstin_lookup_legal_name"] = ""
                st.session_state["billing_gstin_lookup_trade_name"] = ""
                st.session_state["billing_gstin_lookup_status_kind"] = "unknown"

            st.subheader("2. Customer Billing Details")
            customer_name = st.text_input("Customer / Business Name", key="billing_customer_name")
            customer_address = st.text_area("Billing Address", key="billing_customer_address")
            customer_phone = st.text_input("Customer Phone", key="billing_customer_phone")

            st.subheader("3. Supply Details")
            supply_type_label = st.radio(
                "Type of sale",
                ["Intra-state (CGST + SGST)", "Inter-state (IGST)"],
                horizontal=True,
                key="billing_supply_type",
            )
            supply_type = "intra" if supply_type_label.startswith("Intra-state") else "inter"
            place_of_supply = st.text_input(
                "Place of Supply (State/UT)",
                placeholder="e.g., Uttarakhand",
                key="billing_place_of_supply",
            )

            st.subheader("Select Products")
            selected_products = st.multiselect(
                "Choose one or more products",
                options=list(product_options.keys()),
                key="billing_selected_products",
            )

            invoice_items_to_save = []
            taxable_total = 0.0
            cgst_total = 0.0
            sgst_total = 0.0
            igst_total = 0.0

            if selected_products:
                st.subheader("Item Details")
                st.caption("Prices are before GST. Tax is added to each line total.")
                for product_label in selected_products:
                    product_id = product_options[product_label]
                    product_row = available_products[available_products["id"] == product_id].iloc[0]
                    stock = int(product_row["quantity"])
                    price = float(product_row["price"])
                    gst_rate = float(product_row.get("gst_rate", 18) or 0)

                    col1, col2, col3 = st.columns([3, 2, 2])
                    with col1:
                        st.write(f"**{product_row['name']}**")
                        st.caption(f"Taxable unit price: Rs.{price:,.2f} | GST: {gst_rate:g}%")
                    with col2:
                        quantity = st.number_input(
                            "Quantity", min_value=1, max_value=stock, value=1,
                            step=1, key=f"billing_qty_{product_id}",
                        )

                    line_taxable = round(int(quantity) * price, 2)
                    line_tax = round(line_taxable * gst_rate / 100, 2)
                    if supply_type == "intra":
                        line_cgst = round(line_tax / 2, 2)
                        line_sgst = round(line_tax - line_cgst, 2)
                        line_igst = 0.0
                    else:
                        line_cgst = 0.0
                        line_sgst = 0.0
                        line_igst = line_tax
                    line_total = round(line_taxable + line_tax, 2)

                    with col3:
                        st.write("**Including GST**")
                        st.write(f"Rs.{line_total:,.2f}")

                    invoice_items_to_save.append({
                        "product_id": product_id,
                        "product_name": str(product_row["name"]),
                        "quantity": int(quantity),
                        "unit_price": price,
                        "subtotal": line_taxable,
                        "gst_rate": gst_rate,
                        "taxable_value": line_taxable,
                        "cgst_amount": line_cgst,
                        "sgst_amount": line_sgst,
                        "igst_amount": line_igst,
                        "total_amount": line_total,
                    })
                    taxable_total += line_taxable
                    cgst_total += line_cgst
                    sgst_total += line_sgst
                    igst_total += line_igst

            grand_total = round(taxable_total + cgst_total + sgst_total + igst_total, 2)
            if invoice_items_to_save:
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("Taxable Value", f"Rs.{taxable_total:,.2f}")
                if supply_type == "intra":
                    c2.metric("CGST + SGST", f"Rs.{cgst_total + sgst_total:,.2f}")
                else:
                    c2.metric("IGST", f"Rs.{igst_total:,.2f}")
                c3.metric("Invoice Total", f"Rs.{grand_total:,.2f}")
                with st.expander("View GST breakup"):
                    st.write(f"CGST: Rs.{cgst_total:,.2f}")
                    st.write(f"SGST: Rs.{sgst_total:,.2f}")
                    st.write(f"IGST: Rs.{igst_total:,.2f}")

            if st.button("Save GST Invoice", type="primary"):
                if not customer_name.strip():
                    st.error("Please enter the customer name.")
                elif buyer_registered == "Registered" and not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", buyer_gstin):
                    st.error("Please enter a correctly formatted buyer GSTIN, or mark the buyer as Unregistered.")
                elif not place_of_supply.strip():
                    st.error("Please enter the place of supply.")
                elif not invoice_items_to_save:
                    st.error("Please select at least one product.")
                else:
                    try:
                        with get_connection() as conn:
                            next_number = conn.execute(
                                "SELECT COUNT(*) FROM invoices"
                            ).fetchone()[0] + 1
                            invoice_number = f"INV-{next_number:04d}"
                            first_item = invoice_items_to_save[0]
                            invoice_columns = {
                                row[1] for row in conn.execute("PRAGMA table_info(invoices)").fetchall()
                            }
                            insert_columns = [
                                "invoice_number", "customer_name", "product_id",
                                "product_name", "quantity", "unit_price", "subtotal",
                                "customer_address", "customer_phone", "buyer_registered", "buyer_gstin", "supply_type",
                                "place_of_supply", "taxable_total", "cgst_total",
                                "sgst_total", "igst_total", "grand_total",
                            ]
                            insert_values = [
                                invoice_number, customer_name.strip(), first_item["product_id"],
                                first_item["product_name"], first_item["quantity"],
                                first_item["unit_price"], taxable_total,
                                customer_address.strip(), customer_phone.strip(), buyer_registered,
                                buyer_gstin if buyer_registered == "Registered" else "", supply_type,
                                place_of_supply.strip(), taxable_total, cgst_total,
                                sgst_total, igst_total, grand_total,
                            ]
                            # These fields are added by setup_database; this guard gives a clearer error if migration was skipped.
                            missing = [col for col in insert_columns if col not in invoice_columns]
                            if missing:
                                raise RuntimeError("Database migration is missing fields: " + ", ".join(missing) + ". Restart the app and try again.")
                            placeholders = ", ".join(["?"] * len(insert_columns))
                            conn.execute(
                                f"INSERT INTO invoices ({', '.join(insert_columns)}) VALUES ({placeholders})",
                                insert_values,
                            )
                            invoice_id = conn.execute(
                                "SELECT id FROM invoices WHERE invoice_number = ?", (invoice_number,)
                            ).fetchone()[0]

                            for item in invoice_items_to_save:
                                cursor = conn.execute(
                                    "UPDATE products SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                                    (item["quantity"], item["product_id"], item["quantity"]),
                                )
                                if cursor.rowcount != 1:
                                    raise ValueError(f"Insufficient stock for {item['product_name']}. No invoice was saved.")
                                conn.execute(
                                    """INSERT INTO invoice_items (
                                        invoice_id, product_id, product_name, quantity,
                                        unit_price, subtotal, gst_rate, taxable_value,
                                        cgst_amount, sgst_amount, igst_amount, total_amount
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                    (
                                        invoice_id, item["product_id"], item["product_name"],
                                        item["quantity"], item["unit_price"], item["subtotal"],
                                        item["gst_rate"], item["taxable_value"], item["cgst_amount"],
                                        item["sgst_amount"], item["igst_amount"], item["total_amount"],
                                    ),
                                )
                        st.success(f"Invoice {invoice_number} saved. Total payable: Rs.{grand_total:,.2f}")
                        st.rerun()
                    except (ValueError, RuntimeError) as error:
                        st.error(str(error))
                    except sqlite3.IntegrityError:
                        st.error("The invoice could not be saved due to a database constraint. Please check the invoice number and database migration.")

    st.divider()
    st.subheader("Saved Invoices")
    with get_connection() as conn:
        saved_invoices = pd.read_sql_query("""
            SELECT i.invoice_number, i.customer_name,
                   COUNT(ii.id) AS number_of_items,
                   COALESCE(SUM(ii.quantity), 0) AS total_units,
                   CASE WHEN COALESCE(MAX(i.grand_total), 0) > 0
                        THEN MAX(i.grand_total)
                        ELSE COALESCE(SUM(ii.subtotal), i.subtotal) END AS grand_total,
                   i.created_at
            FROM invoices AS i
            LEFT JOIN invoice_items AS ii ON ii.invoice_id = i.id
            GROUP BY i.id ORDER BY i.id DESC
        """, conn)

    if saved_invoices.empty:
        st.info("No invoices saved yet.")
    else:
        display_invoices = saved_invoices.copy()
        display_invoices["grand_total"] = display_invoices["grand_total"].map(lambda value: f"Rs.{value:,.2f}")
        st.dataframe(display_invoices, use_container_width=True, hide_index=True)
        st.subheader("View Invoice Items")
        invoice_numbers = saved_invoices["invoice_number"].tolist()
        selected_invoice = st.selectbox("Choose an invoice", invoice_numbers, key="view_invoice_selector")

        with get_connection() as conn:
            invoice_details = pd.read_sql_query("""
                SELECT ii.product_name AS Product, ii.quantity AS Quantity,
                       ii.unit_price AS [Unit Price], ii.gst_rate AS [GST Rate %],
                       ii.taxable_value AS [Taxable Value],
                       (ii.cgst_amount + ii.sgst_amount + ii.igst_amount) AS [GST Amount],
                       CASE WHEN ii.total_amount > 0 THEN ii.total_amount ELSE ii.subtotal END AS [Line Total]
                FROM invoice_items AS ii JOIN invoices AS i ON i.id = ii.invoice_id
                WHERE i.invoice_number = ? ORDER BY ii.id
            """, conn, params=(selected_invoice,))

        if not invoice_details.empty:
            for col in ("Unit Price", "Taxable Value", "GST Amount", "Line Total"):
                invoice_details[col] = invoice_details[col].map(lambda value: f"Rs.{value:,.2f}")
            invoice_details["GST Rate %"] = invoice_details["GST Rate %"].map(lambda value: f"{value:g}%")
            st.dataframe(invoice_details, use_container_width=True, hide_index=True)

        st.subheader("Download Invoice PDF")
        if st.button("Generate PDF", key="generate_invoice_pdf"):
            try:
                with get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    invoice = conn.execute(
                        "SELECT * FROM invoices WHERE invoice_number = ?",
                        (selected_invoice,),
                    ).fetchone()
                    profile = conn.execute(
                        "SELECT business_name, address, phone, email, gstin, logo_path FROM business_profile WHERE id = 1"
                    ).fetchone()
                    pdf_items = conn.execute(
                        """SELECT product_name, quantity, unit_price, subtotal, gst_rate,
                                  taxable_value, cgst_amount, sgst_amount, igst_amount, total_amount
                           FROM invoice_items WHERE invoice_id = (
                               SELECT id FROM invoices WHERE invoice_number = ?
                           ) ORDER BY id""",
                        (selected_invoice,),
                    ).fetchall()

                if not invoice:
                    st.error("Invoice not found.")
                elif not pdf_items:
                    st.error("No item details were found for this invoice.")
                elif not profile or not str(profile["business_name"] or "").strip():
                    st.error(
                        "Please complete Business Profile first. Save your business name, "
                        "address, phone, email and GSTIN (if registered), then generate the PDF again."
                    )
                else:
                    pdf_buffer = BytesIO()
                    document = SimpleDocTemplate(
                        pdf_buffer, pagesize=A4,
                        rightMargin=14 * mm, leftMargin=14 * mm,
                        topMargin=12 * mm, bottomMargin=16 * mm,
                        title=f"GST Invoice {selected_invoice}",
                        author=str(profile["business_name"]),
                    )
                    styles = getSampleStyleSheet()
                    styles["Normal"].fontName = "Helvetica"
                    styles["Normal"].fontSize = 8.5
                    styles["Normal"].leading = 11
                    styles.add(ParagraphStyle(
                        name="InvoiceSmall", parent=styles["Normal"],
                        fontSize=7.5, leading=9, textColor=colors.HexColor("#475569")
                    ))
                    styles.add(ParagraphStyle(
                        name="InvoiceBusiness", parent=styles["Heading1"],
                        fontSize=15, leading=18, textColor=colors.HexColor("#163A5F"),
                        spaceAfter=2 * mm
                    ))
                    styles.add(ParagraphStyle(
                        name="InvoiceSection", parent=styles["Heading3"],
                        fontSize=9, leading=11, textColor=colors.HexColor("#163A5F"),
                        spaceAfter=1 * mm
                    ))
                    styles.add(ParagraphStyle(
                        name="InvoiceLabel", parent=styles["Normal"],
                        fontSize=7.5, leading=9, textColor=colors.HexColor("#475569")
                    ))
                    styles.add(ParagraphStyle(
                        name="InvoiceTotal", parent=styles["Normal"],
                        fontSize=10, leading=13, textColor=colors.HexColor("#163A5F")
                    ))
                    story = []

                    def money(value):
                        return f"Rs. {float(value or 0):,.2f}"

                    business_name = str(profile["business_name"] or "").strip()
                    profile_lines = [Paragraph(f"<b>{label}:</b> {escape(str(profile[field]))}", styles["Normal"])
                                     for field, label in (("address", "Address"), ("phone", "Phone"),
                                                          ("email", "Email"), ("gstin", "GSTIN"))
                                     if str(profile[field] or "").strip()]
                    details = [Paragraph(escape(business_name), styles["InvoiceBusiness"])] + profile_lines
                    logo_cell = ""
                    logo_path = str(profile["logo_path"] or "").strip()
                    if logo_path and Path(logo_path).is_file():
                        try:
                            logo_cell = PDFImage(logo_path, width=24 * mm, height=24 * mm, kind="proportional")
                        except Exception:
                            logo_cell = ""
                    header = Table([[logo_cell, details]], colWidths=[29 * mm, 151 * mm], hAlign="LEFT")
                    header.setStyle(TableStyle([
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor("#163A5F")),
                    ]))
                    story.extend([header, Spacer(1, 5 * mm)])

                    try:
                        invoice_date = pd.to_datetime(invoice["created_at"]).strftime("%d-%m-%Y")
                    except Exception:
                        invoice_date = str(invoice["created_at"] or "")
                    supply_type = str(invoice["supply_type"] or "")
                    supply_label = ("Intra-state (CGST + SGST)" if supply_type == "intra"
                                    else "Inter-state (IGST)" if supply_type == "inter"
                                    else "Legacy invoice — GST not recorded")
                    meta_rows = [
                        [Paragraph("<b>GST TAX INVOICE</b>", styles["InvoiceSection"]),
                         Paragraph(f"<b>Invoice No.:</b> {escape(str(invoice['invoice_number']))}", styles["Normal"])],
                        [Paragraph(f"<b>Supply:</b> {escape(supply_label)}", styles["Normal"]),
                         Paragraph(f"<b>Date:</b> {escape(invoice_date)}", styles["Normal"])],
                    ]
                    if str(invoice["place_of_supply"] or "").strip():
                        meta_rows.append([Paragraph(f"<b>Place of Supply:</b> {escape(str(invoice['place_of_supply']))}", styles["Normal"]), ""])
                    meta = Table(meta_rows, colWidths=[90 * mm, 90 * mm], hAlign="LEFT")
                    meta.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]))
                    story.extend([meta, Spacer(1, 4 * mm)])

                    customer_name_text = str(invoice["customer_name"] or "").strip() or "Customer name not provided"
                    customer_address_text = str(invoice["customer_address"] or "").strip() or "Not provided"
                    customer_phone_text = str(invoice["customer_phone"] or "").strip() or "Not provided"
                    customer_rows = [
                        [Paragraph("<b>BILL TO</b>", styles["InvoiceSection"]),
                         Paragraph(f"<b>{escape(customer_name_text)}</b>", styles["Normal"])],
                        [Paragraph("Buyer GST Status", styles["InvoiceLabel"]),
                         Paragraph(escape(str(invoice["buyer_registered"] or "Unknown")), styles["Normal"])],
                    ]
                    if str(invoice["buyer_gstin"] or "").strip():
                        customer_rows.append([Paragraph("Buyer GSTIN", styles["InvoiceLabel"]),
                                              Paragraph(escape(str(invoice["buyer_gstin"])), styles["Normal"])])
                    customer_rows.extend([
                        [Paragraph("Address", styles["InvoiceLabel"]),
                         Paragraph(escape(customer_address_text), styles["Normal"])],
                        [Paragraph("Phone", styles["InvoiceLabel"]),
                         Paragraph(escape(customer_phone_text), styles["Normal"])],
                    ])
                    customer = Table(customer_rows, colWidths=[25 * mm, 155 * mm], hAlign="LEFT")
                    customer.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]))
                    story.extend([customer, Spacer(1, 5 * mm)])

                    table_data = [["Product / Description", "Qty", "Rate", "GST %", "Taxable Value", "GST", "Line Total"]]
                    pdf_taxable = pdf_cgst = pdf_sgst = pdf_igst = pdf_total = 0.0
                    for item in pdf_items:
                        taxable = float(item["taxable_value"] or 0)
                        if taxable == 0 and float(item["subtotal"] or 0) > 0:
                            taxable = float(item["subtotal"])
                        cgst = float(item["cgst_amount"] or 0)
                        sgst = float(item["sgst_amount"] or 0)
                        igst = float(item["igst_amount"] or 0)
                        gst = cgst + sgst + igst
                        total = float(item["total_amount"] or 0) or (taxable + gst)
                        pdf_taxable += taxable
                        pdf_cgst += cgst
                        pdf_sgst += sgst
                        pdf_igst += igst
                        pdf_total += total
                        table_data.append([
                            Paragraph(escape(str(item["product_name"] or "")), styles["Normal"]),
                            str(item["quantity"]), money(item["unit_price"]),
                            f"{float(item['gst_rate'] or 0):g}%", money(taxable), money(gst), money(total),
                        ])
                    item_table = Table(table_data,
                        colWidths=[43 * mm, 10 * mm, 22 * mm, 14 * mm, 29 * mm, 22 * mm, 30 * mm],
                        repeatRows=1, hAlign="LEFT")
                    item_table.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163A5F")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 7),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]))
                    story.extend([item_table, Spacer(1, 4 * mm)])

                    summary_rows = [["Taxable Value", money(pdf_taxable)]]
                    if supply_type == "intra":
                        summary_rows.extend([["CGST", money(pdf_cgst)], ["SGST", money(pdf_sgst)]])
                    elif supply_type == "inter":
                        summary_rows.append(["IGST", money(pdf_igst)])
                    summary_rows.append([Paragraph("<b>Grand Total</b>", styles["InvoiceTotal"]),
                                         Paragraph(f"<b>{money(pdf_total)}</b>", styles["InvoiceTotal"])])
                    summary = Table(summary_rows, colWidths=[42 * mm, 35 * mm], hAlign="RIGHT")
                    summary.setStyle(TableStyle([
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF1F8")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]))
                    story.extend([summary, Spacer(1, 12 * mm),
                                  Paragraph("Authorized Signature: ______________________________", styles["Normal"]),
                                  Spacer(1, 4 * mm),
                                  Paragraph("Thank you for your business.", styles["InvoiceSmall"])])
                    document.build(story)
                    pdf_buffer.seek(0)
                    st.download_button(
                        "Download GST Invoice PDF", data=pdf_buffer.getvalue(),
                        file_name=f"{selected_invoice}.pdf", mime="application/pdf",
                    )
            except Exception as error:
                st.error(f"Could not generate the PDF: {error}")

elif section == "Party Ledger":
    st.title("👥 Party Ledger")
    st.info("Customer, supplier, and payment records will be added later.")

elif section == "Accounting":
    st.title("📚 Accounting")
    st.info("Double-entry accounting and financial statements are planned.")

elif section == "GST & Tax":
    st.title("🇮🇳 GST & Tax")
    st.write("GST billing is enabled for new invoices using product-level GST rates.")
    st.info("Default GST rate for new products is 18%. Confirm the correct rate for each product. GST calculations are a prototype and do not file returns or verify legal tax treatment automatically.")
    st.write("For a taxable value of Rs.1,000 at 18% GST, tax is Rs.180 and the total is Rs.1,180.")
    st.write("For intra-state sales, this prototype splits GST equally into CGST and SGST. For inter-state sales, it applies IGST.")

elif section == "AI Assistant":
    st.title("🤖 SMART CA AI Assistant")
    question = st.text_input(
        "Ask a business or accounting question",
        placeholder="Example: What is a balance sheet?",
    )
    if st.button("Submit Question"):
        if question.strip():
            st.info("AI service connection will be added in a later stage.")
        else:
            st.warning("Please enter a question.")

st.divider()
st.caption("SMART CA • Prototype • Sample inventory data is fictional.")
def test_gstinapi_account():
    api_key = os.getenv("SMART_CA_GST_API_KEY", "").strip()

    if not api_key:
        api_key = str(
            st.secrets.get("SMART_CA_GST_API_KEY", "")
        ).strip()

    if not api_key:
        print("API key not found")
        return

    url = "https://www.gstinapi.in/v1/gstin/stats/me"
    request = urllib.request.Request(
        url,
        headers={"x-api-key": api_key, "Accept": "application/json"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print("HTTP status:", response.status)
            print("Response:", response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print("HTTP status:", exc.code)
        print("Response:", exc.read().decode("utf-8"))
        