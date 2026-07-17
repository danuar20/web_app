from flask import Blueprint, make_response, render_template, request, redirect, url_for, session, flash, jsonify
from app.db.db_webapp import get_connection
from ._utils import login_required, admin_required, json_response, db_query, _no_cache
import logging

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin_bp", __name__, url_prefix="/admin")


# ── User List ─────────────────────────────────────────────────────────────────
@admin_bp.route("/users")
@login_required
@admin_required
def user_list():
    try:
        with db_query(get_connection) as (conn, cur):
            # Get users with their active session counts
            cur.execute("""
                SELECT
                    u.id,
                    u.username,
                    u.role,
                    u.is_active,
                    u.failed_attempts,
                    u.locked_until,
                    u.max_session,
                    COUNT(s.id) FILTER (WHERE s.expires_at > NOW()) AS active_sessions
                FROM users u
                LEFT JOIN user_sessions s ON s.user_id = u.id
                GROUP BY u.id, u.username, u.role, u.is_active,
                         u.failed_attempts, u.locked_until, u.max_session
                ORDER BY u.id
            """)
            rows = cur.fetchall()

        users = []
        for row in rows:
            (uid, username, role, is_active, failed_attempts,
             locked_until, max_session, active_sessions) = row

            # Determine lock status
            is_locked = False
            if locked_until is not None:
                try:
                    from datetime import timezone
                    import datetime
                    now = datetime.datetime.now(timezone.utc)
                    # Make locked_until timezone-aware if not already
                    if locked_until.tzinfo is None:
                        locked_until = locked_until.replace(tzinfo=timezone.utc)
                    is_locked = locked_until > now
                except Exception:
                    is_locked = False

            users.append({
                "id":              uid,
                "username":        username,
                "role":            role,
                "is_active":       is_active,
                "failed_attempts": failed_attempts,
                "locked_until":    locked_until.strftime("%Y-%m-%d %H:%M:%S %Z") if locked_until and is_locked else None,
                "is_locked":       is_locked,
                "max_session":     max_session,
                "active_sessions": active_sessions or 0,
            })

        response = make_response(render_template(
            "admin_users.html",
            users=users,
            username=session["username"],
            role=session.get("role", "admin"),
        ))
        return _no_cache(response)

    except Exception as e:
        flash(f"Failed to load user list: {e}", "danger")
        return redirect(url_for("auth.home_page"))


# ── Toggle Active (block / unblock) ───────────────────────────────────────────
@admin_bp.route("/users/<int:user_id>/toggle_active", methods=["POST"])
@login_required
@admin_required
def toggle_active(user_id):
    # Prevent admin from deactivating themselves
    if user_id == session.get("user_id"):
        flash("You cannot deactivate your own account.", "warning")
        return redirect(url_for("admin_bp.user_list"))

    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute(
                "UPDATE users SET is_active = NOT is_active WHERE id = %s RETURNING username, is_active",
                (user_id,)
            )
            row = cur.fetchone()
            conn.commit()

        if row:
            username, new_state = row
            state_label = "activated" if new_state else "deactivated"
            flash(f"User '{username}' has been {state_label}.", "success")
        else:
            flash("User not found.", "danger")
    except Exception as e:
        flash(f"Error updating user: {e}", "danger")

    return redirect(url_for("admin_bp.user_list"))


# ── Unlock user (reset lock + failed_attempts) ─────────────────────────────────
@admin_bp.route("/users/<int:user_id>/unlock", methods=["POST"])
@login_required
@admin_required
def unlock_user(user_id):
    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute(
                """
                UPDATE users
                SET failed_attempts = 0, locked_until = NULL
                WHERE id = %s
                RETURNING username
                """,
                (user_id,)
            )
            row = cur.fetchone()
            conn.commit()

        if row:
            flash(f"User '{row[0]}' has been unlocked.", "success")
        else:
            flash("User not found.", "danger")
    except Exception as e:
        flash(f"Error unlocking user: {e}", "danger")

    return redirect(url_for("admin_bp.user_list"))


# ── Kill all sessions for a user ──────────────────────────────────────────────
@admin_bp.route("/users/<int:user_id>/kill_sessions", methods=["POST"])
@login_required
@admin_required
def kill_sessions(user_id):
    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                flash("User not found.", "danger")
                return redirect(url_for("admin_bp.user_list"))

            username = row[0]
            cur.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))
            conn.commit()

        flash(f"All sessions for '{username}' have been terminated.", "success")
    except Exception as e:
        flash(f"Error killing sessions: {e}", "danger")

    return redirect(url_for("admin_bp.user_list"))


# ── Update max_session for a user ─────────────────────────────────────────────
@admin_bp.route("/users/<int:user_id>/update_max_session", methods=["POST"])
@login_required
@admin_required
def update_max_session(user_id):
    try:
        new_max = int(request.form.get("max_session", 5))
        if new_max < 1:
            new_max = 1
    except (ValueError, TypeError):
        flash("Invalid max session value.", "danger")
        return redirect(url_for("admin_bp.user_list"))

    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute(
                "UPDATE users SET max_session = %s WHERE id = %s RETURNING username",
                (new_max, user_id)
            )
            row = cur.fetchone()
            conn.commit()

        if row:
            flash(f"Max sessions for '{row[0]}' updated to {new_max}.", "success")
        else:
            flash("User not found.", "danger")
    except Exception as e:
        flash(f"Error updating max session: {e}", "danger")

    return redirect(url_for("admin_bp.user_list"))


# ── Recent Login Logs ──────────────────────────────────────────────────────────
@admin_bp.route("/users/login_logs")
@login_required
@admin_required
def login_logs():
    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute("""
                SELECT username, ip_address, user_agent, status, attempted_at,
                       location, isp, cpu_cores, ram_gb, gpu_info
                FROM login_logs
                ORDER BY attempted_at DESC
                LIMIT 200
            """)
            rows = cur.fetchall()

        logs = [
            {
                "username":     r[0],
                "ip_address":   r[1],
                "user_agent":   r[2][:80],
                "status":       r[3],
                "attempted_at": r[4].strftime("%Y-%m-%d %H:%M:%S") if r[4] else "-",
                "location":     r[5] or "Unknown",
                "isp":          r[6] or "Unknown",
                "cpu_cores":    r[7] or "?",
                "ram_gb":       r[8] or "?",
                "gpu_info":     r[9][:30] + "..." if r[9] and len(r[9]) > 30 else (r[9] or "Unknown"),
            }
            for r in rows
        ]

        response = make_response(render_template(
            "admin_users.html",
            users=None,
            logs=logs,
            username=session["username"],
            role=session.get("role", "admin"),
            view="logs",
        ))
        return _no_cache(response)

    except Exception as e:
        flash(f"Failed to load login logs: {e}", "danger")
        return redirect(url_for("admin_bp.user_list"))
