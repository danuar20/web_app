<div align="center">
  <h1>📡 NetKPI Monitor</h1>
  <p><strong>Advanced Network Performance & KPI Analytics Dashboard</strong></p>
  
  <p>
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version" />
    <img src="https://img.shields.io/badge/Flask-2.x-lightgrey.svg" alt="Flask" />
    <img src="https://img.shields.io/badge/PostgreSQL-14+-blue.svg" alt="PostgreSQL" />
    <img src="https://img.shields.io/badge/Frontend-Vanilla_JS-yellow.svg" alt="JavaScript" />
  </p>
</div>

---

NetKPI Monitor is a comprehensive, highly responsive web application built with **Flask** and **PostgreSQL**. It is designed for telecommunication engineers and network administrators to monitor, analyze, and optimize mobile network performance across **2G, 4G, and 5G** technologies.

## ✨ Key Features

### 📊 Multi-Technology Dashboards (2G / 4G / 5G)
- **Executive Summaries**: High-level overviews of Payload, Traffic, and Accessibility metrics.
- **Trend Analysis**: Interactive daily and hourly charting using `Chart.js`.
- **Top Contributors**: Instant identification of top-performing and worst-performing regions or cells.

### 📈 Granular KPI Monitoring
- **Hierarchical Drill-down**: Filter and analyze data across multiple network layers: **Regional** ➔ **NOP** ➔ **City** ➔ **BSC/RNC** ➔ **Site/Cell**.
- **Dynamic Filtering**: Cascading drop-downs with real-time UI updates via AJAX.
- **Metric Tracking**: Track critical KPIs including CSSR, CCSR, HOSR, Drop Rates, and Resource Blocking.

### 🚨 Worst Performing Cell (WPC) Analysis
- **Client-Side OLAP**: Fetch raw datasets once and interactively filter/aggregate without hitting the database repeatedly.
- **Toggle Base**: Seamlessly switch WPC rankings between **Percentage (%)** and absolute **Fail Numbers**.
- **Top 10 Insights**: Automated tables isolating the heaviest contributors to network degradation.

### 🛠️ Productivity & Optimization
- **Year-Over-Year Analytics**: Track Payload and Traffic growth.
- **Site Level Deep Dives**: Drill into specific site behaviors over custom timeframes.
- **Exporting**: One-click **CSV Downloads** and high-resolution **PNG Snapshot Exports** (via `html2canvas`) for reporting.

### 🔒 Administration & Security
- **Role-Based Access**: Secure login system with bcrypt password hashing and session management.
- **User Management**: Built-in Admin dashboard to create, disable, and manage analyst accounts.

---

## 🏗️ Technology Stack

| Component | Technology | Description |
| :--- | :--- | :--- |
| **Backend** | Python & Flask | RESTful APIs, routing, and session management. |
| **Database** | PostgreSQL | Robust relational data storage, querying via `psycopg2`. |
| **Frontend** | HTML5, CSS3, Vanilla JS | Lightweight, dynamic DOM manipulation without bulky frameworks. |
| **Charting** | Chart.js | Responsive, interactive data visualization. |

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10 or higher
- PostgreSQL Server

### 2. Environment Setup

Clone the repository and create a Python virtual environment:

```bash
git clone https://github.com/yourusername/netkpi-monitor.git
cd netkpi-monitor/Web-server/web_app

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Database Credentials

Copy the environment template and update it with your actual PostgreSQL credentials:

```bash
cp .env.example .env
```

Edit the `.env` file:
```ini
FLASK_ENV=development
FLASK_SECRET_KEY=your-secure-secret-key-here

# Application DB (Users, Sessions)
WEBAPP_DB_HOST=localhost
WEBAPP_DB_PORT=5432
WEBAPP_DB_NAME=webapp_db
WEBAPP_DB_USER=your-user
WEBAPP_DB_PASSWORD=your-password

# KPI Source DBs
POSTGRES_DB_HOST=localhost
POSTGRES_DB_PORT=5432
POSTGRES_DB_NAME=postgres
POSTGRES_DB_USER=your-user
POSTGRES_DB_PASSWORD=your-password
```

### 5. Create Initial Admin User

Run the CLI script to generate your first login credential:

```bash
python scripts/create_user.py
```
*(Follow the interactive prompts)*

### 6. Launch the Application

Start the Flask development server:

```bash
python run.py
```
Navigate to **`http://localhost:5000`** in your browser!

---

## 📁 Project Structure

```text
web_app/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── routes/              # Modular blueprint routes (Dashboard, Auth, KPI)
│   └── db/                  # Database connection pooling utilities
├── scripts/                 # CLI tools (User creation, DB aggregations, ETL)
├── static/                  # Static assets (Custom CSS, JS helpers, Images)
├── templates/               # Jinja2 HTML templates
├── .env                     # Environment variables (Ignored by Git)
├── requirements.txt         # Python dependencies
└── run.py                   # Application entry point
```

---

## 📸 Screenshots

*(Add your screenshots here before publishing!)*

| Dashboard Overview | WPC Analysis |
|:---:|:---:|
| `<img src="path/to/dashboard.png" width="400"/>` | `<img src="path/to/wpc.png" width="400"/>` |

---

## 🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](../../issues).

## 📝 License
This project is proprietary and confidential. All rights reserved.
