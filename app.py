from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date, timedelta
import sqlite3, secrets, string, os
from database import get_db, init_db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-demo-secret-change-before-deployment")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

SLOT_TIMES = [f"{h:02d}:{m:02d}" for h in range(11, 22) for m in (0, 30)]
RESERVATION_MINUTES = 90

def current_user():
    if not session.get("user_id"):
        return None
    conn = get_db()
    user = conn.execute("SELECT id,name,email,phone,role FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return user

@app.context_processor
def inject_globals():
    return {"current_user": current_user(), "today": date.today().isoformat()}

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "admin":
            flash("Administrator access is required.", "error")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def make_reference():
    alphabet = string.ascii_uppercase + string.digits
    return "TT-" + "".join(secrets.choice(alphabet) for _ in range(7))

def parse_slot(date_str, time_str):
    start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    end = start + timedelta(minutes=RESERVATION_MINUTES)
    return start, end

def available_tables(conn, date_str, time_str, guests, exclude_reservation_id=None):
    start, end = parse_slot(date_str, time_str)
    sql = """
        SELECT t.* FROM restaurant_tables t
        WHERE t.is_active=1 AND t.capacity >= ?
          AND NOT EXISTS (
            SELECT 1 FROM reservations r
            WHERE r.table_id=t.id
              AND r.reservation_date=?
              AND r.status IN ('PENDING','CONFIRMED')
              AND r.start_time < ?
              AND r.end_time > ?
    """
    params = [guests, date_str, end.strftime("%H:%M"), start.strftime("%H:%M")]
    if exclude_reservation_id:
        sql += " AND r.id != ?"
        params.append(exclude_reservation_id)
    sql += ") ORDER BY t.capacity ASC, t.table_number ASC"
    return conn.execute(sql, params).fetchall()

def award_points(conn, user_id, reservation_id, points, reason):
    conn.execute(
        "INSERT INTO loyalty_accounts(user_id, points, lifetime_points) VALUES(?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET points=points+excluded.points, lifetime_points=lifetime_points+excluded.lifetime_points",
        (user_id, points, points)
    )
    conn.execute(
        "INSERT INTO loyalty_transactions(user_id,points_change,reason,reservation_id) VALUES(?,?,?,?)",
        (user_id, points, reason, reservation_id)
    )

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not name or not email or not phone or len(password) < 8:
            flash("Complete every field. Passwords must be at least 8 characters.", "error")
            return render_template("auth.html", mode="register")
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO users(name,email,phone,password_hash,role) VALUES(?,?,?,?, 'customer')",
                (name, email, phone, generate_password_hash(password))
            )
            conn.execute("INSERT INTO loyalty_accounts(user_id) VALUES(?)", (cur.lastrowid,))
            conn.commit()
            session["user_id"] = cur.lastrowid
            flash("Account created. Welcome to Table & Thyme.", "success")
            return redirect(url_for("my_reservations"))
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("An account with that email already exists.", "error")
        finally:
            conn.close()
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name'].split()[0]}.", "success")
            target = request.args.get("next")
            if user["role"] == "admin":
                return redirect(target or url_for("admin_dashboard"))
            return redirect(target or url_for("my_reservations"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))

@app.route("/book", methods=["GET", "POST"])
@login_required
def book():
    if request.method == "POST":
        date_str = request.form.get("reservation_date", "")
        time_str = request.form.get("start_time", "")
        guests = request.form.get("guests", "2")
        occasion = request.form.get("occasion", "").strip()
        notes = request.form.get("notes", "").strip()
        try:
            guests = int(guests)
            start, end = parse_slot(date_str, time_str)
            if date.fromisoformat(date_str) < date.today():
                raise ValueError()
            if time_str not in SLOT_TIMES or guests < 1 or guests > 8:
                raise ValueError()
        except (ValueError, TypeError):
            flash("Choose a valid future date, time and party size (1–8 guests).", "error")
            return render_template("book.html", slots=SLOT_TIMES, min_date=date.today().isoformat())

        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            tables = available_tables(conn, date_str, time_str, guests)
            if not tables:
                conn.rollback()
                flash("No suitable table is available for that time. Try another slot or party size.", "error")
                return render_template("book.html", slots=SLOT_TIMES, min_date=date.today().isoformat())
            table = tables[0]
            ref = make_reference()
            cur = conn.execute(
                """INSERT INTO reservations(reference,user_id,table_id,reservation_date,start_time,end_time,guests,occasion,notes,status)
                   VALUES(?,?,?,?,?,?,?,?,?,'CONFIRMED')""",
                (ref, session["user_id"], table["id"], date_str, time_str, end.strftime("%H:%M"), guests, occasion, notes)
            )
            rid = cur.lastrowid
            conn.execute(
                "INSERT INTO reservation_history(reservation_id,old_status,new_status,changed_by,note) VALUES(?,NULL,'CONFIRMED',?,'Customer booking')",
                (rid, session["user_id"])
            )
            # Points are awarded once for a successful booking; this is a demo loyalty rule.
            award_points(conn, session["user_id"], rid, 25, f"Reservation reward · {ref}")
            conn.commit()
            flash(f"Reservation confirmed. Your reference is {ref}. You earned 25 loyalty points.", "success")
            return redirect(url_for("reservation_detail", reference=ref))
        except sqlite3.Error:
            conn.rollback()
            flash("We couldn't save the reservation. Please try again.", "error")
        finally:
            conn.close()
    return render_template("book.html", slots=SLOT_TIMES, min_date=date.today().isoformat())

@app.route("/availability")
def availability():
    date_str = request.args.get("date", "")
    time_str = request.args.get("time", "")
    try:
        guests = int(request.args.get("guests", "2"))
        if date.fromisoformat(date_str) < date.today() or time_str not in SLOT_TIMES or not 1 <= guests <= 8:
            raise ValueError()
        conn = get_db()
        tables = available_tables(conn, date_str, time_str, guests)
        result = [{"table_number": t["table_number"], "capacity": t["capacity"], "area": t["area"]} for t in tables]
        conn.close()
        return jsonify({"available": result, "count": len(result)})
    except ValueError:
        return jsonify({"error": "Invalid date, time or guest count."}), 400

@app.route("/my-reservations")
@login_required
def my_reservations():
    conn = get_db()
    reservations = conn.execute("""
        SELECT r.*, t.table_number, t.area
        FROM reservations r JOIN restaurant_tables t ON t.id=r.table_id
        WHERE r.user_id=? ORDER BY r.reservation_date DESC, r.start_time DESC
    """, (session["user_id"],)).fetchall()
    loyalty = conn.execute("SELECT * FROM loyalty_accounts WHERE user_id=?", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("my_reservations.html", reservations=reservations, loyalty=loyalty)

@app.route("/reservation/<reference>")
@login_required
def reservation_detail(reference):
    conn = get_db()
    reservation = conn.execute("""
        SELECT r.*, t.table_number, t.area, u.name, u.email, u.phone
        FROM reservations r JOIN restaurant_tables t ON t.id=r.table_id
        JOIN users u ON u.id=r.user_id WHERE r.reference=?
    """, (reference,)).fetchone()
    conn.close()
    user = current_user()
    if not reservation or (user["role"] != "admin" and reservation["user_id"] != user["id"]):
        flash("Reservation not found.", "error")
        return redirect(url_for("my_reservations"))
    return render_template("reservation_detail.html", reservation=reservation)

@app.route("/reservation/<reference>/cancel", methods=["POST"])
@login_required
def cancel_reservation(reference):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT * FROM reservations WHERE reference=?", (reference,)).fetchone()
        user = current_user()
        if not r or (user["role"] != "admin" and r["user_id"] != user["id"]):
            conn.rollback()
            flash("Reservation not found.", "error")
        elif r["status"] not in ("PENDING", "CONFIRMED"):
            conn.rollback()
            flash("This reservation can no longer be cancelled.", "warning")
        else:
            conn.execute("UPDATE reservations SET status='CANCELLED' WHERE id=?", (r["id"],))
            conn.execute(
                "INSERT INTO reservation_history(reservation_id,old_status,new_status,changed_by,note) VALUES(?,?,?,?,?)",
                (r["id"], r["status"], "CANCELLED", user["id"], "Cancellation")
            )
            conn.commit()
            flash("Reservation cancelled. The table is now available for that time.", "success")
    except sqlite3.Error:
        conn.rollback()
        flash("Unable to cancel this reservation.", "error")
    finally:
        conn.close()
    return redirect(url_for("reservation_detail", reference=reference))

@app.route("/loyalty")
@login_required
def loyalty():
    conn = get_db()
    account = conn.execute("SELECT * FROM loyalty_accounts WHERE user_id=?", (session["user_id"],)).fetchone()
    transactions = conn.execute("SELECT * FROM loyalty_transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (session["user_id"],)).fetchall()
    rewards = conn.execute("SELECT * FROM rewards WHERE is_active=1 ORDER BY points_cost",).fetchall()
    redemptions = conn.execute("""
        SELECT rr.*, rw.name AS reward_name FROM reward_redemptions rr
        JOIN rewards rw ON rw.id=rr.reward_id WHERE rr.user_id=? ORDER BY rr.created_at DESC
    """, (session["user_id"],)).fetchall()
    conn.close()
    points = account["points"] if account else 0
    tier = "Bronze" if points < 250 else ("Silver" if points < 600 else "Gold")
    return render_template("loyalty.html", account=account, transactions=transactions, rewards=rewards, redemptions=redemptions, tier=tier)

@app.route("/loyalty/redeem/<int:reward_id>", methods=["POST"])
@login_required
def redeem_reward(reward_id):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        account = conn.execute("SELECT * FROM loyalty_accounts WHERE user_id=?", (session["user_id"],)).fetchone()
        reward = conn.execute("SELECT * FROM rewards WHERE id=? AND is_active=1", (reward_id,)).fetchone()
        if not reward or not account or account["points"] < reward["points_cost"]:
            conn.rollback()
            flash("You don't have enough points for that reward.", "error")
        else:
            code = "RW-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
            conn.execute("UPDATE loyalty_accounts SET points=points-? WHERE user_id=?", (reward["points_cost"], session["user_id"]))
            conn.execute(
                "INSERT INTO loyalty_transactions(user_id,points_change,reason) VALUES(?,?,?)",
                (session["user_id"], -reward["points_cost"], f"Redeemed: {reward['name']}")
            )
            conn.execute(
                "INSERT INTO reward_redemptions(user_id,reward_id,points_spent,redemption_code) VALUES(?,?,?,?)",
                (session["user_id"], reward_id, reward["points_cost"], code)
            )
            conn.commit()
            flash(f"Reward redeemed. Your code is {code}.", "success")
    except sqlite3.Error:
        conn.rollback()
        flash("Unable to redeem this reward.", "error")
    finally:
        conn.close()
    return redirect(url_for("loyalty"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    today_str = date.today().isoformat()
    total = conn.execute("SELECT COUNT(*) FROM reservations WHERE status IN ('PENDING','CONFIRMED')").fetchone()[0]
    today_count = conn.execute("SELECT COUNT(*) FROM reservations WHERE reservation_date=? AND status IN ('PENDING','CONFIRMED')", (today_str,)).fetchone()[0]
    customers = conn.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0]
    active_tables = conn.execute("SELECT COUNT(*) FROM restaurant_tables WHERE is_active=1").fetchone()[0]
    today_bookings = conn.execute("""
        SELECT r.*, u.name AS customer_name, u.phone, t.table_number
        FROM reservations r JOIN users u ON u.id=r.user_id JOIN restaurant_tables t ON t.id=r.table_id
        WHERE r.reservation_date=? ORDER BY r.start_time LIMIT 10
    """, (today_str,)).fetchall()
    upcoming = conn.execute("""
        SELECT r.*, u.name AS customer_name, t.table_number
        FROM reservations r JOIN users u ON u.id=r.user_id JOIN restaurant_tables t ON t.id=r.table_id
        WHERE r.reservation_date>=? AND r.status IN ('PENDING','CONFIRMED')
        ORDER BY r.reservation_date,r.start_time LIMIT 8
    """, (today_str,)).fetchall()
    conn.close()
    occupancy = round((today_count / active_tables) * 100) if active_tables else 0
    return render_template("admin_dashboard.html", total=total, today_count=today_count, customers=customers,
                           active_tables=active_tables, today_bookings=today_bookings, upcoming=upcoming, occupancy=min(occupancy,100))

@app.route("/admin/reservations")
@admin_required
def admin_reservations():
    status = request.args.get("status", "")
    date_filter = request.args.get("date", "")
    q = request.args.get("q", "").strip()
    sql = """SELECT r.*, u.name AS customer_name,u.email,u.phone,t.table_number
             FROM reservations r JOIN users u ON u.id=r.user_id JOIN restaurant_tables t ON t.id=r.table_id WHERE 1=1"""
    params = []
    if status:
        sql += " AND r.status=?"; params.append(status)
    if date_filter:
        sql += " AND r.reservation_date=?"; params.append(date_filter)
    if q:
        sql += " AND (u.name LIKE ? OR r.reference LIKE ? OR u.phone LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    sql += " ORDER BY r.reservation_date DESC,r.start_time DESC"
    conn = get_db()
    reservations = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template("admin_reservations.html", reservations=reservations, status=status, date_filter=date_filter, q=q)

@app.route("/admin/reservations/<int:rid>/status", methods=["POST"])
@admin_required
def admin_update_status(rid):
    new_status = request.form.get("status", "")
    allowed = {"PENDING", "CONFIRMED", "CANCELLED", "COMPLETED", "NO_SHOW"}
    if new_status not in allowed:
        flash("Invalid status.", "error")
        return redirect(url_for("admin_reservations"))
    user = current_user()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
        if not r:
            conn.rollback()
            flash("Reservation not found.", "error")
        elif new_status in ("PENDING", "CONFIRMED"):
            conflicts = conn.execute("""
                SELECT COUNT(*) FROM reservations
                WHERE table_id=? AND reservation_date=? AND status IN ('PENDING','CONFIRMED')
                  AND start_time < ? AND end_time > ? AND id != ?
            """, (r["table_id"], r["reservation_date"], r["end_time"], r["start_time"], rid)).fetchone()[0]
            if conflicts:
                conn.rollback()
                flash("Cannot reactivate this reservation because the table has a conflicting booking.", "error")
            else:
                conn.execute("UPDATE reservations SET status=? WHERE id=?", (new_status, rid))
                conn.execute("INSERT INTO reservation_history(reservation_id,old_status,new_status,changed_by,note) VALUES(?,?,?,?,?)",
                             (rid, r["status"], new_status, user["id"], "Admin status update"))
                conn.commit()
                flash("Reservation status updated.", "success")
        else:
            conn.execute("UPDATE reservations SET status=? WHERE id=?", (new_status, rid))
            conn.execute("INSERT INTO reservation_history(reservation_id,old_status,new_status,changed_by,note) VALUES(?,?,?,?,?)",
                         (rid, r["status"], new_status, user["id"], "Admin status update"))
            conn.commit()
            flash("Reservation status updated.", "success")
    except sqlite3.Error:
        conn.rollback()
        flash("Unable to update status.", "error")
    finally:
        conn.close()
    return redirect(url_for("admin_reservations"))

@app.route("/admin/tables", methods=["GET", "POST"])
@admin_required
def admin_tables():
    conn = get_db()
    if request.method == "POST":
        number = request.form.get("table_number", "").strip().upper()
        try:
            capacity = int(request.form.get("capacity", "0"))
            area = request.form.get("area", "Main Dining").strip() or "Main Dining"
            if not number or capacity < 1 or capacity > 20:
                raise ValueError()
            conn.execute("INSERT INTO restaurant_tables(table_number,capacity,area) VALUES(?,?,?)", (number, capacity, area))
            conn.commit()
            flash("Table added.", "success")
        except ValueError:
            conn.rollback()
            flash("Enter a table number and a capacity between 1 and 20.", "error")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("That table number already exists.", "error")
        finally:
            conn.close()
        return redirect(url_for("admin_tables"))
    tables = conn.execute("""
        SELECT t.*,
        (SELECT COUNT(*) FROM reservations r WHERE r.table_id=t.id AND r.status IN ('PENDING','CONFIRMED') AND r.reservation_date>=?) AS upcoming_count
        FROM restaurant_tables t ORDER BY t.table_number
    """, (date.today().isoformat(),)).fetchall()
    conn.close()
    return render_template("admin_tables.html", tables=tables)

@app.route("/admin/tables/<int:tid>/toggle", methods=["POST"])
@admin_required
def toggle_table(tid):
    conn = get_db()
    row = conn.execute("SELECT * FROM restaurant_tables WHERE id=?", (tid,)).fetchone()
    if row:
        new_active = 0 if row["is_active"] else 1
        conn.execute("UPDATE restaurant_tables SET is_active=? WHERE id=?", (new_active, tid))
        conn.commit()
        flash("Table status updated.", "success")
    conn.close()
    return redirect(url_for("admin_tables"))

@app.route("/admin/customers")
@admin_required
def admin_customers():
    conn = get_db()
    customers = conn.execute("""
        SELECT u.id,u.name,u.email,u.phone,u.created_at,COALESCE(l.points,0) AS points,
        (SELECT COUNT(*) FROM reservations r WHERE r.user_id=u.id) AS reservation_count
        FROM users u LEFT JOIN loyalty_accounts l ON l.user_id=u.id
        WHERE u.role='customer' ORDER BY u.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("admin_customers.html", customers=customers)

@app.route("/admin/reports")
@admin_required
def admin_reports():
    conn = get_db()
    by_day = conn.execute("""
        SELECT reservation_date, COUNT(*) AS bookings,
        SUM(CASE WHEN status='CANCELLED' THEN 1 ELSE 0 END) AS cancelled
        FROM reservations WHERE reservation_date>=date('now','-13 day')
        GROUP BY reservation_date ORDER BY reservation_date
    """).fetchall()
    by_slot = conn.execute("""
        SELECT start_time, COUNT(*) AS bookings FROM reservations
        WHERE status IN ('PENDING','CONFIRMED') AND reservation_date>=?
        GROUP BY start_time ORDER BY bookings DESC LIMIT 6
    """, (date.today().isoformat(),)).fetchall()
    status_counts = conn.execute("SELECT status,COUNT(*) AS total FROM reservations GROUP BY status").fetchall()
    top_customers = conn.execute("""
        SELECT u.name,COUNT(r.id) AS total FROM users u JOIN reservations r ON r.user_id=u.id
        WHERE u.role='customer' GROUP BY u.id ORDER BY total DESC LIMIT 5
    """).fetchall()
    conn.close()
    return render_template("admin_reports.html", by_day=by_day, by_slot=by_slot, status_counts=status_counts, top_customers=top_customers)

@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
