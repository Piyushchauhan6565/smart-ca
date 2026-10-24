# 📊 SMART CA — Smart Business & Accounting Assistant

**An AI-powered inventory, billing, party ledger, accounting, and GST management application for businesses.**

SMART CA is a Python-based business management application designed to simplify everyday business operations through a centralized dashboard. The project aims to bring inventory management, invoicing, accounting, and GST-related workflows into one place.

## 🚀 Features

- **Dashboard:** Central access to business management modules.
- **Business Profile:** Store business details used for billing.
- **Inventory Management:** Manage products, prices, and stock quantities.
- **Billing System:** Create invoices containing multiple products.
- **GST Calculations:** Calculate GST for intra-state and inter-state transactions.
- **PDF Invoices:** Generate printable invoice documents.
- **Party Ledger:** Manage party-related records.
- **Accounting:** Dedicated accounting module.
- **GSTIN Lookup:** Buyer GST registration lookup interface.
- **AI Assistant:** An assistant interface for business-related questions.

## 🛠️ Technology Stack

- **Language:** Python
- **User Interface:** Streamlit
- **Database:** SQLite
- **Data Processing:** Pandas
- **PDF Generation:** ReportLab

## 💻 Getting Started

### Prerequisites

- Python installed on your computer
- Git
- Visual Studio Code (recommended)

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/Piyushchauhan6565/smart-ca.git
   ```

2. Open the project directory:

   ```bash
   cd smart-ca
   ```

3. Create a virtual environment:

   ```bash
   python -m venv .venv
   ```

4. Install the required packages used by the project:

   ```bash
   python -m pip install streamlit pandas reportlab
   ```

5. Run the application:

   ```bash
   python -m streamlit run app.py
   ```

## 🔐 Security and Data

- Keep API keys and credentials out of source control.
- Do not commit `.streamlit/secrets.toml`, database files, or real customer data.
- Configure external API credentials locally through Streamlit secrets.
- Verify GST registration details through reliable sources before relying on them for business transactions.

## 🗺️ Development Roadmap

- [x] Set up the Python development environment
- [x] Build the Streamlit application interface
- [x] Integrate the SQLite database
- [x] Implement inventory and stock management
- [x] Implement multi-product billing
- [x] Implement GST calculations and invoice PDF generation
- [ ] Complete party ledger and outstanding balances
- [ ] Improve live GSTIN verification and eliminate demo responses
- [ ] Improve inventory alerts and stock history
- [ ] Add automated tests and strengthen data protection
- [ ] Improve documentation and user guidance

*The checklist reflects the current development plan and should be updated as features are verified.*

## 📌 Project Status

SMART CA is under active development. Features and integrations are being improved and tested as the project progresses.

## 🤝 Contributing

Suggestions, bug reports, and feature requests are welcome. Please open an issue in the GitHub repository to discuss an improvement.

## 📄 License

A license has not yet been specified. All rights are reserved by default unless a license is added to this repository.
