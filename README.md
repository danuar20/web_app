# NetKPI Monitor

A Flask-based web dashboard for monitoring network KPI metrics.

## Setup Instructions

### 1. Create Python Virtual Environment

```bash
cd Web-server/web_app
python -m venv venv
```

**On Windows:**
```bash
venv\Scripts\activate
```

**On macOS/Linux:**
```bash
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and update with your database credentials:

```bash
cp .env.example .env
```

Edit `.env` with your database information:

```
FLASK_ENV=development
FLASK_SECRET_KEY=your-secure-secret-key-here

WEBAPP_DB_HOST=your-host
WEBAPP_DB_PORT=5432
WEBAPP_DB_NAME=webapp_db
WEBAPP_DB_USER=your-user
WEBAPP_DB_PASSWORD=your-password

POSTGRES_DB_HOST=your-host
POSTGRES_DB_PORT=5432
POSTGRES_DB_NAME=postgres
POSTGRES_DB_USER=your-user
POSTGRES_DB_PASSWORD=your-password

PUMAZ_DB_HOST=your-host
PUMAZ_DB_PORT=5432
PUMAZ_DB_NAME=pumazdb
PUMAZ_DB_USER=your-user
PUMAZ_DB_PASSWORD=your-password
```

### 4. Create Database User

Run the setup script to create a test user:

```bash
python create_user.py
```

Follow the prompts to create your login credentials.

### 5. Run the Application

```bash
python run.py
```

The app will start on `http://localhost:5000`

---

## Features

- **Dashboard** — Overview of network status
- **Productivity** — Year-over-year traffic & payload analysis
- **City Level** — City-level KPI metrics
- **Site Level** — Site-level KPI metrics
- **4G KPI Hourly** — Hourly 4G performance metrics (CSSR & Payload)

---

## Architecture

```
web_app/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── routes.py            # Blueprint with all routes
│   ├── db/
│   │   ├── db_webapp.py     # Webapp database connection
│   │   ├── db_pumaz.py      # Pumaz database connection
│   │   └── db_webapp.py     # PostgreSQL connection
│   ├── auth/
│   ├── static/              # CSS, JS, images
│   └── templates/           # HTML templates
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variables template
├── run.py                   # Entry point
└── create_user.py           # User creation utility
```

---

## Database Connections

The app connects to **3 separate databases**:

1. **Webapp DB** — User authentication & basic data
2. **Pumaz DB** — Traffic & payload historical data (remote)
3. **PostgreSQL** — 4G KPI real-time metrics

---

## Troubleshooting

❌ **"Cannot connect to database"**
- Check `.env` file credentials
- Verify database servers are online
- Confirm firewall allows connection

❌ **"No data showing"**
- Check date ranges (ensure data exists in that period)
- Verify NSA/City/Site filters are properly selected

❌ **"Chart not rendering"**
- Check browser console (F12 → Console tab)
- Ensure Chart.js CDN is loading

---

## Notes

- Database credentials should be kept in `.env` file (never commit to git)
- Session timeout is set in Flask—adjust if needed
- Chart styling uses dark/light theme from localStorage
