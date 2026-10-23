# 📊 SMART CA — Smart Business & Accounting Assistant

**An AI-powered inventory, billing, party ledger, and GST management system for businesses and accounting professionals.**

SMART CA is a Python-based business management application designed to simplify everyday operations through a single dashboard.

## 🚀 Current Features

- **Dashboard:** Central interface for accessing business modules.
- **Business Profile:** Maintain business information used for billing.
- **Inventory Management:** Manage products, prices, and stock.
- **Billing System:** Create invoices containing multiple products.
- **GST Billing:** Calculate applicable GST for intra-state and inter-state transactions.
- **PDF Invoices:** Generate printable invoice documents.
- **Party Ledger:** Dedicated module for party-related records.
- **Accounting:** Dedicated accounting module.
- **AI Assistant:** Planned and ongoing development of business-focused assistance.
- **GSTIN Lookup:** Integration under development to retrieve and validate buyer details through an external provider.

> **Development status:** SMART CA is an MVP under active development. Some modules and integrations may be incomplete. Always verify GST details and tax calculations before issuing a real invoice.

## 🛠️ Technology Stack

- Python
- Streamlit
- SQLite
- Pandas
- ReportLab
- External GST verification API (integration in progress)

## 💻 Run Locally

### Prerequisites

- Python installed
- Git installed
- Visual Studio Code (recommended)

### Setup

Clone the repository:

```bash
git clone https://github.com/Piyushchauhan6565/smart-ca.git
cd smart-ca
```

Create a virtual environment:

```bash
python -m venv .venv
```

Install dependencies:

```bash
python -m pip install streamlit pandas reportlab
```

Run the application:

```bash
python -m streamlit run app.py
```

Open the local URL displayed in the terminal.

## 🔐 Security

- Never commit API keys, passwords, or private credentials.
- Keep `.streamlit/secrets.toml` out of Git.
- Do not upload real customer information or the local business database to a public repository.
- Verify customer GSTIN and registration details through reliable sources.

## 🗺️ Development Roadmap

- [x] Initial Python development environment
- [x] Streamlit application interface
- [x] SQLite database integration
- [x] Inventory and stock deduction
- [x] Multi-product billing
- [x] GST calculation and PDF invoices
- [x] Buyer GST lookup interface
- [ ] Reliable live GSTIN verification
- [ ] Improved party ledger and accounting workflows
- [ ] Automated testing and validation
- [ ] Deployment and production security improvements

## 📅 Development Updates

Progress will be documented through GitHub commits, Issues, and milestone updates.

## 👨‍💻 Maintainer

**Piyush Chauhan**

GitHub: [@Piyushchauhan6565](https://github.com/Piyushchauhan6565)

---

*SMART CA is an ongoing learning and development project. Features and workflows may change as development progresses.*
