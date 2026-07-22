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






# 2G Monitoring — /kpi_2g_monitoring (daily agg, 5 dimension tabs)
from . import kpi_2g_monitoring_routes
kpi2g_monitoring = kpi_2g_monitoring_routes.kpi2g_monitoring

# WPC 2G Monitoring
from . import wpc_2g_monitoring_routes
wpc_2g_monitoring = wpc_2g_monitoring_routes.wpc_2g_monitoring

from . import wpc_4g_monitoring_routes
wpc_4g_monitoring = wpc_4g_monitoring_routes.wpc_4g_monitoring

# 4G Monitoring — /kpi_4g_monitoring (import before dashboards that depend on it)
from . import kpi_4g_monitoring_routes
kpi4g_monitoring = kpi_4g_monitoring_routes.kpi4g_monitoring

# 5G Monitoring — /kpi_5g_monitoring (import before dashboards that depend on it)
from . import kpi_5g_monitoring_routes
kpi5g_monitoring = kpi_5g_monitoring_routes.kpi5g_monitoring

# Dashboard 4G — /dashboard_4g
from . import dashboard_4g_routes
dashboard_4g = dashboard_4g_routes.dashboard_4g

# Dashboard 2G — /dashboard_2g
from . import dashboard_2g_routes
dashboard_2g = dashboard_2g_routes.dashboard_2g

# Dashboard 5G — /dashboard_5g
from . import dashboard_5g_routes
dashboard_5g = dashboard_5g_routes.dashboard_5g








# TA 4G New — /ta_4g_new
from . import ta_4g_new_routes
ta4g_new = ta_4g_new_routes.ta4g_new





# Coverage Simulation — /coverage_simulation
from . import coverage_routes
coverage = coverage_routes.coverage

# Okumura-Hata Model — /okumura_hata
from . import okumura_hata_routes
okumura_hata = okumura_hata_routes.okumura_hata

# NetTilt 3D — /nettilt3d
from . import nettilt3d_routes
nettilt3d = nettilt3d_routes.nettilt3d

# Admin — /admin/users, /admin/users/login_logs
from . import admin_routes
admin_bp = admin_routes.admin_bp

# PL Monitoring — /pl_monitoring
from . import pl_monitoring_routes
pl_monitoring = pl_monitoring_routes.pl_monitoring

# Optim 4G
from . import optim_4g_routes
optim_4g = optim_4g_routes.optim_4g
