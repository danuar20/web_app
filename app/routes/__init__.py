# Routes package — all blueprints are imported here so app/__init__.py
# can register them in one place.
from flask import Blueprint

# Auth — home, login, logout, dashboard, health, api/cities, api/sites
from . import auth_routes
auth = auth_routes.auth

# Dashboard — served by auth_routes (same blueprint)
# Productivity — /productivity, /city_level, /site_level
from . import productivity_routes
prod = productivity_routes.prod

# 2G KPI Daily — /kpi_2g_daily (BSC Level & Site Level)
from . import kpi_2g_daily_routes
kpi2g_daily = kpi_2g_daily_routes.kpi2g_daily

# 2G KPI Hourly — /kpi_2g_hourly (BSC Level & Site Level)
from . import kpi_2g_hourly_routes
kpi2g_hourly = kpi_2g_hourly_routes.kpi2g_hourly

# 2G KPI Hourly Sector — /kpi_2g_hourly_sector
from . import kpi_2g_hourly_sector_routes
kpi2g_hourly_sector = kpi_2g_hourly_sector_routes.kpi2g_hourly_sector

# 2G KPI Hourly Compare — /kpi_2g_hourly/compare
from . import kpi_2g_compare_routes
kpi2g_compare = kpi_2g_compare_routes.kpi2g_compare

# 2G KPI Hourly Trend — /kpi_2g_hourly/trend
from . import kpi_2g_trend_routes
kpi2g_trend = kpi_2g_trend_routes.kpi2g_trend

# 4G KPI Daily — /kpi_4g_daily
from . import kpi_4g_daily_routes
kpi4g_daily = kpi_4g_daily_routes.kpi4g_daily

# 4G KPI Hourly — /kpi_4g_hourly (per-site view)
from . import kpi_4g_hourly_routes
kpi4g_hourly = kpi_4g_hourly_routes.kpi4g_hourly

# 4G KPI Hourly Sector — /kpi_4g_hourly_sector
from . import kpi_4g_hourly_sector_routes
kpi4g_hourly_sector = kpi_4g_hourly_sector_routes.kpi4g_hourly_sector

# 4G KPI Hourly Trend — /kpi_4g_hourly/trend (cluster aggregation)
from . import kpi_4g_trend_routes
kpi4g_trend = kpi_4g_trend_routes.kpi4g_trend

# 4G KPI Hourly Compare — /kpi_4g_hourly/compare (before/after comparison)
from . import kpi_4g_compare_routes
kpi4g_compare = kpi_4g_compare_routes.kpi4g_compare

# 4G KPI API & Export — /api/kpi_4g_hourly, /export/kpi_4g_hourly
from . import kpi_4g_api_routes
kpi4g_api = kpi_4g_api_routes.kpi4g_api

# Packet Loss — /pl_2g, /pl_4g, /api/pl_4g, /export/pl_2g, /export/pl_4g
from . import packet_loss_routes
pl = packet_loss_routes.pl

# TA 4G — /ta_4g
from . import ta_4g_routes
ta4g = ta_4g_routes.ta4g

# 5G KPI Daily — /kpi_5g_daily (per-site view)
from . import kpi_5g_daily_routes
kpi5g_daily = kpi_5g_daily_routes.kpi5g_daily

# 5G KPI Hourly — /kpi_5g_hourly (per-site view)
from . import kpi_5g_hourly_routes
kpi5g_hourly = kpi_5g_hourly_routes.kpi5g_hourly

# 5G KPI Hourly Sector — /kpi_5g_hourly_sector
from . import kpi_5g_hourly_sector_routes
kpi5g_hourly_sector = kpi_5g_hourly_sector_routes.kpi5g_hourly_sector

# 5G KPI Hourly Compare — /kpi_5g_hourly/compare
from . import kpi_5g_compare_routes
kpi5g_compare = kpi_5g_compare_routes.kpi5g_compare

# Coverage Simulation — /coverage_simulation
from . import coverage_routes
coverage = coverage_routes.coverage

# Okumura-Hata Model — /okumura_hata
from . import okumura_hata_routes
okumura_hata = okumura_hata_routes.okumura_hata

# NetTilt 3D — /nettilt3d
from . import nettilt3d_routes
nettilt3d = nettilt3d_routes.nettilt3d