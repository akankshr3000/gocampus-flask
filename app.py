"""
GoCampus Flask app with Cloudinary QR upload + PostgreSQL (Neon)
"""
# force rebuild 

import os
import io
import re
import traceback
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session,
    jsonify, send_file
)
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
import segno
import cloudinary
import cloudinary.uploader

# ----------------------------------------------------
# CLOUDINARY CONFIG
# ----------------------------------------------------
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")

if CLOUDINARY_URL:
    cloudinary.config(secure=True)
    print("Cloudinary configured using CLOUDINARY_URL")
else:
    print("WARNING: CLOUDINARY_URL not found. Cloud uploads disabled.")

# ----------------------------------------------------
# FLASK APP
# ----------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev_secret")

# ----------------------------------------------------
# POSTGRESQL DATABASE HELPER
# ----------------------------------------------------
def get_db():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is missing")
    return psycopg2.connect(url, sslmode="require")

# ----------------------------------------------------
# FILE PATHS
# ----------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_PATH = os.path.join(BASE_DIR, "backend_qrcodes")
PHOTO_PATH = os.path.join(BASE_DIR, "static", "student_photos")
COLLEGE_LOGO_PRIMARY = os.path.join(BASE_DIR, "static", "college_logo", "bitm_logo.png")
FALLBACK_LOGO_1 = os.path.join(BASE_DIR, "static", "college_logo", "fallback1.png")
FALLBACK_LOGO_2 = os.path.join(BASE_DIR, "static", "college_logo", "fallback2.png")

os.makedirs(QR_PATH, exist_ok=True)
os.makedirs(PHOTO_PATH, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static", "college_logo"), exist_ok=True)

# ----------------------------------------------------
# UTILITY HELPERS
# ----------------------------------------------------
def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r'\D', '', phone)
    if len(digits) > 10:
        digits = digits[-10:]
    return digits

def format_phone_display(phone: str) -> str:
    digits = normalize_phone(phone)
    if len(digits) == 10:
        return f"+91 {digits[:5]} {digits[5:]}"
    return phone or ""

def validate_bus_id(bus_id):
    if not bus_id:
        return False, "Bus No is required"
    if not bus_id.isdigit():
        return False, "Bus No must contain only digits"
    return True, ""

def validate_phone(phone):
    digits = normalize_phone(phone)
    if not digits:
        return True, ""
    if len(digits) != 10:
        return False, "Phone number must be exactly 10 digits"
    if len(set(digits)) == 1:
        return False, "Phone number cannot use repeated digits"
    if not digits.isdigit():
        return False, "Phone number must contain only digits"
    return True, ""

def format_date(date_str):
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d-%m-%Y")
    except:
        return date_str

# ----------------------------------------------------
# GENERATE STUDENT ID (Postgres Version)
# ----------------------------------------------------
def generate_student_id():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    DELETE FROM help_tickets
    WHERE status = 'Resolved'
    AND resolved_at::timestamp <= NOW() - INTERVAL '5 days'
""")

    result = cur.fetchone()
    conn.close()

    last_num = result[0] if result and result[0] else 0
    return f"S{last_num + 1:02d}"

# ----------------------------------------------------
# QR GENERATION + CLOUDINARY UPLOAD
# ----------------------------------------------------
def generate_secure_qr(student_id: str):
    try:
        qr = segno.make(student_id, error='h')

        qr_buffer = io.BytesIO()
        qr.save(qr_buffer, kind='png', scale=20, border=4)
        qr_buffer.seek(0)
        qr_img = Image.open(qr_buffer).convert("RGBA")

        target_size = 1500
        qr_img = qr_img.resize((target_size, target_size), resample=Image.NEAREST)

        final = Image.new("RGBA", qr_img.size, (255, 255, 255, 255))

        watermark_text = "Ballari Institute of Technology and Management"
        try:
            font = ImageFont.truetype("arial.ttf", 35)
            font_small = ImageFont.truetype("arial.ttf", 20)
        except:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()

        watermark_layer = Image.new("RGBA", final.size, (255,255,255,0))
        opacity = int(255 * 0.08)

        tmp = Image.new("RGBA", (final.width, 100), (255,255,255,0))
        tmp_draw = ImageDraw.Draw(tmp)
        bbox = tmp_draw.textbbox((0,0), watermark_text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tmp_draw.text(((final.width - text_w)//2, (100 - text_h)//2),
                      watermark_text, fill=(0,0,0,opacity), font=font)
        rotated = tmp.rotate(30, expand=True)

        for y in range(-rotated.height, final.height + rotated.height, rotated.height + 120):
            for x in range(-rotated.width, final.width + rotated.width, rotated.width + 120):
                watermark_layer.paste(rotated, (x,y), rotated)

        final = Image.alpha_composite(final, watermark_layer)
        qr_rgb = qr_img.convert("RGB")
        final_rgb = final.convert("RGB")
        final_rgb.paste(qr_rgb, (0,0))
        final = final_rgb.convert("RGBA")

        # logo paste
        logo_candidates = [COLLEGE_LOGO_PRIMARY, FALLBACK_LOGO_1, FALLBACK_LOGO_2]
        logo_path = next((p for p in logo_candidates if os.path.exists(p)), None)
        if logo_path:
            try:
                logo = Image.open(logo_path).convert("RGBA")
                lw, lh = logo.size
                s = max(lw, lh)
                tmp_logo = Image.new("RGBA", (s,s), (255,255,255,0))
                tmp_logo.paste(logo, ((s-lw)//2, (s-lh)//2), logo)
                logo = tmp_logo

                logo_size = int(final.width * 0.17)
                logo = logo.resize((logo_size, logo_size), resample=Image.LANCZOS)
                pad = int(logo_size * 0.12)
                bg_size = (logo_size + pad*2, logo_size + pad*2)
                bg = Image.new("RGBA", bg_size, (255,255,255,255))
                bg_draw = ImageDraw.Draw(bg)
                radius = int(min(bg_size)//5)
                bg_draw.rounded_rectangle((0,0,bg_size[0],bg_size[1]),
                                          radius=radius, fill=(255,255,255,255))
                bg_pos = ((final.width - bg_size[0])//2, (final.height - bg_size[1])//2)
                logo_pos = (bg_pos[0] + pad, bg_pos[1] + pad)
                final.paste(bg, bg_pos, bg)
                final.paste(logo, logo_pos, logo)
            except:
                pass

        # micro text
        border_draw = ImageDraw.Draw(final)
        border_text = "BITM • " * 50
        border_offset = 50
        border_draw.text((border_offset, 10), border_text, font=font_small, fill=(0,0,0,255))
        bbox_b = border_draw.textbbox((0,0), border_text, font=font_small)
        h_text = bbox_b[3] - bbox_b[1]
        border_draw.text((border_offset, final.height - h_text - 10),
                         border_text, font=font_small, fill=(0,0,0,255))

        # save memory
        mem = io.BytesIO()
        final.save(mem, format="PNG")
        mem.seek(0)

        # CLOUDINARY UPLOAD
        if CLOUDINARY_URL:
            try:
                upload_result = cloudinary.uploader.upload(
                    mem,
                    folder="gocampus_qr",
                    public_id=student_id,
                    overwrite=True,
                    resource_type="image"
                )
                print("CLOUDINARY UPLOAD RESULT:", upload_result)
                return upload_result.get("secure_url")
            except Exception as e:
                print("Cloudinary upload error:", e)

        # fallback
        local_path = os.path.join(QR_PATH, f"{student_id}.png")
        final.save(local_path, format="PNG")
        return local_path

    except Exception:
        traceback.print_exc()
        raise
# ----------------------------------------------------
# ROUTES START
# ----------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


# ----------------------- VERIFY PAGE -----------------------
@app.route('/verify', methods=['GET'])
def verify_page():
    return render_template('verify_qr_public.html')


@app.route('/verify', methods=['POST'])
def verify():
    student_id = request.form.get('student_id')

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT name, fee_paid FROM students WHERE student_id = %s", (student_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return render_template('result.html', message="Student not found ❌", color="red")

    name, paid = row

    cur.execute("""
        SELECT student_id, name, bus_id, fee_paid, parent_contact, semester,
               branch, amount_paid, transaction_date, email, photo_filename, qr_url
        FROM students
        WHERE student_id = %s
    """, (student_id,))
    full_row = cur.fetchone()
    conn.close()

    student = None
    if full_row:
        student = {
            'student_id': full_row[0],
            'name': full_row[1],
            'bus_id': full_row[2],
            'fee_paid': full_row[3],
            'parent_contact': format_phone_display(full_row[4]),
            'semester': full_row[5],
            'branch': full_row[6],
            'amount_paid': full_row[7],
            'transaction_date': format_date(full_row[8]) if full_row[8] else None,
            'email': full_row[9],
            'photo_url': url_for('static', filename=f'student_photos/{full_row[10]}') if full_row[10] else None,
            'qr_url': full_row[11]
        }

    if paid:
        return render_template(
            'result.html',
            message=f"✅ Access Granted — {name} has paid.",
            color="green",
            student=student
        )
    else:
        return render_template(
            'result.html',
            message=f"🚫 Access Denied — {name} has NOT paid.",
            color="red",
            student=student
        )


# ----------------------- ADMIN LOGIN -----------------------
@app.route('/admin', methods=['GET'])
def admin_page():
    return render_template('admin_login.html')


@app.route('/admin_login', methods=['POST'])
def admin_login():
    username = request.form.get('username')
    password = request.form.get('password')

    if username == "admin" and password == "12345":
        session['admin'] = username
        return redirect(url_for('admin_dashboard'))

    flash("Invalid credentials ❌")
    return redirect(url_for('admin_page'))


# ----------------------- ADMIN DASHBOARD -----------------------
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Auto delete resolved help tickets older than 5 days
    cur.execute("""
    DELETE FROM help_tickets
    WHERE status = 'Resolved'
    AND resolved_at::timestamp <= NOW() - INTERVAL '5 days'
""") 
    conn.commit()

    cur.execute("""
        SELECT id, student_id, name, bus_id, fee_paid, parent_contact, semester,
               branch, amount_paid, transaction_date, email, photo_filename,
               valid_till, current_sem, qr_url
        FROM students
        ORDER BY student_id
    """)

    rows = cur.fetchall()
    conn.close()

    students = []
    renewal_alerts = []

    for r in rows:
        r = dict(r)
        r["parent_contact"] = format_phone_display(r["parent_contact"])
        students.append(r)

        # renewal date
        valid_till = r["valid_till"]
        if valid_till:
            try:
                dt = datetime.strptime(valid_till, "%Y-%m-%d")
                days_left = (dt - datetime.now()).days
                if days_left <= 30:
                    renewal_alerts.append({
                        "student_id": r["student_id"],
                        "name": r["name"],
                        "valid_till": format_date(valid_till),
                        "is_expired": days_left < 0
                    })
            except:
                pass

    paid_count = sum(1 for s in students if s["fee_paid"] == 1)
    unpaid_count = sum(1 for s in students if s["fee_paid"] == 0)

    chart_data = {
        'paid': paid_count,
        'unpaid': unpaid_count,
        'total': paid_count + unpaid_count
    }

    return render_template(
        'admin_dashboard.html',
        students=students,
        chart_data=chart_data,
        renewal_alerts=renewal_alerts
    )

# ----------------------------------------------------
# ADD STUDENT
# ----------------------------------------------------
@app.route('/add_student', methods=['POST'])
def add_student():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))

    student_id = generate_student_id()
    name = request.form.get('name', '').strip()
    bus_id = request.form.get('bus_id', '').strip()
    fee_paid = request.form.get('fee_paid', '0').strip()
    parent_contact_raw = request.form.get('parent_contact', '').strip()
    semester = request.form.get('semester', '').strip()
    branch = request.form.get('branch', '').strip()
    email = request.form.get('email', '').strip()

    errors = []

    if not name:
        errors.append("Name is required")

    ok, err = validate_bus_id(bus_id)
    if not ok:
        errors.append(err)

    ok, err = validate_phone(parent_contact_raw)
    if not ok:
        errors.append(err)

    # Photo validation
    photo_file = request.files.get('photo')
    if not photo_file or photo_file.filename == '':
        errors.append("Student photo is required")

    photo_filename = None
    if photo_file:
        valid, msg = validate_photo(photo_file)
        if not valid:
            errors.append(msg)
        else:
            ext = os.path.splitext(photo_file.filename)[1].lower()
            photo_filename = f"{student_id}{ext}"
            photo_path = os.path.join(PHOTO_PATH, photo_filename)
            try:
                photo_file.seek(0)
                photo_file.save(photo_path)
            except Exception as e:
                errors.append(f"Could not save photo: {e}")

    if errors:
        flash(" | ".join(errors))
        return redirect(url_for('admin_dashboard'))

    # Format data
    phone_digits = normalize_phone(parent_contact_raw)
    parent_contact_db = f"+91{phone_digits}" if phone_digits else None
    fee_val = 1 if fee_paid == "1" else 0

    amount_paid = None
    transaction_date = None

    if fee_val == 1:
        amount_in = request.form.get('amount_paid', '').strip().replace(',', '')
        try:
            amount_paid = int(amount_in)
        except:
            flash("Invalid amount")
            return redirect(url_for('admin_dashboard'))

        if amount_paid != 15000:
            flash("Amount must be exactly ₹15000")
            return redirect(url_for('admin_dashboard'))

        transaction_date = datetime.now().strftime("%Y-%m-%d")

    registration_date = datetime.now().strftime("%Y-%m-%d")
    valid_till = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    current_sem = int(semester) if semester.isdigit() else 1

    # Insert student
    try:
        conn = get_db()
        cur = conn.cursor()

        # Duplicate check
        if parent_contact_db:
            cur.execute("""
                SELECT COUNT(*) FROM students
                WHERE LOWER(name) = LOWER(%s)
                AND parent_contact = %s
            """, (name, parent_contact_db))
            if cur.fetchone()[0] > 0:
                conn.close()
                flash("A student with same name & phone already exists.")
                return redirect(url_for('admin_dashboard'))

        cur.execute("""
            INSERT INTO students (
                student_id, name, bus_id, fee_paid, parent_contact, semester,
                branch, amount_paid, transaction_date, email, photo_filename,
                registration_date, valid_till, current_sem, is_active_transport
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
        """, (
            student_id, name, bus_id, fee_val, parent_contact_db,
            semester, branch, amount_paid, transaction_date,
            email, photo_filename, registration_date, valid_till, current_sem
        ))
        conn.commit()

        # Generate & upload QR
        qr_url = generate_secure_qr(student_id)
        cur.execute("UPDATE students SET qr_url=%s WHERE student_id=%s", (qr_url, student_id))
        conn.commit()

        conn.close()

    except Exception as e:
        flash("Error adding student: " + str(e))
        return redirect(url_for('admin_dashboard'))

    flash(f"Student {name} ({student_id}) added successfully! QR generated.")
    return redirect(url_for('admin_dashboard'))


# ----------------------------------------------------
# GENERATE QR FOR EXISTING STUDENT
# ----------------------------------------------------
@app.route('/generate_qr_admin', methods=['POST'])
def generate_qr_admin():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))

    student_id = request.form.get('student_id')

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT name FROM students WHERE student_id=%s", (student_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        flash("Student ID not found")
        return redirect(url_for('admin_dashboard'))

    name = row[0]

    try:
        qr_url = generate_secure_qr(student_id)
        cur.execute("UPDATE students SET qr_url=%s WHERE student_id=%s", (qr_url, student_id))
        conn.commit()
        conn.close()

        flash(f"QR generated for {name} ({student_id})")

    except Exception as e:
        conn.close()
        flash(f"QR generation failed: {e}")

    return redirect(url_for('admin_dashboard'))


# ----------------------------------------------------
# DELETE STUDENT
# ----------------------------------------------------
@app.route('/delete_student', methods=['POST'])
def delete_student():
    if 'admin' not in session:
        flash("Login required")
        return redirect(url_for('admin_page'))

    student_id = request.form.get('student_id')

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE student_id=%s", (student_id,))
    conn.commit()
    conn.close()

    # Delete local files
    try:
        local_qr = os.path.join(QR_PATH, f"{student_id}.png")
        if os.path.exists(local_qr):
            os.remove(local_qr)
    except:
        pass

    # Delete Cloudinary QR
    try:
        if CLOUDINARY_URL:
            cloudinary.uploader.destroy(
                f"gocampus_qr/{student_id}",
                resource_type="image"
            )
    except:
        pass

    # Delete photo
    for ext in (".jpg", ".jpeg", ".png"):
        p = os.path.join(PHOTO_PATH, f"{student_id}{ext}")
        if os.path.exists(p):
            try:
                os.remove(p)
            except:
                pass

    flash(f"Deleted {student_id}")
    return redirect(url_for('admin_dashboard'))


# ----------------------------------------------------
# MARK PAID
# ----------------------------------------------------
@app.route('/mark_paid_admin', methods=['POST'])
def mark_paid_admin():
    if 'admin' not in session:
        return redirect(url_for('admin_page'))

    student_id = request.form.get('student_id')
    amount = request.form.get('amount_paid', '0').strip().replace(',', '')
    transaction_date = datetime.now().strftime("%Y-%m-%d")

    try:
        amount = int(amount)
    except:
        flash("Invalid amount")
        return redirect(url_for('admin_dashboard'))

    if amount != 15000:
        flash("Amount must be exactly ₹15000")
        return redirect(url_for('admin_dashboard'))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE students
        SET fee_paid=1, amount_paid=%s, transaction_date=%s
        WHERE student_id=%s
    """, (amount, transaction_date, student_id))
    conn.commit()
    conn.close()

    flash(f"{student_id} marked as PAID")
    return redirect(url_for('admin_dashboard'))


# ----------------------------------------------------
# PHONE CHECK
# ----------------------------------------------------
@app.route('/check_phone', methods=['POST'])
def check_phone():
    if 'admin' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    phone_raw = data.get('phone', '').strip()

    if not phone_raw:
        return jsonify({"status":"ok","exists":False})

    phone_digits = normalize_phone(phone_raw)
    if not phone_digits:
        return jsonify({"status":"ok","exists":False})

    phone_db = f"+91{phone_digits}"

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name FROM students WHERE parent_contact=%s", (phone_db,))
    row = cur.fetchone()
    conn.close()

    if row:
        return jsonify({"status":"exists","exists":True,"name":row[0]})

    return jsonify({"status":"ok","exists":False})


# ----------------------------------------------------
# SEARCH STUDENT
# ----------------------------------------------------
@app.route('/search_student', methods=['POST'])
def search_student():
    if 'admin' not in session:
        return jsonify({"error":"Unauthorized"}), 401

    data = request.get_json()
    q = data.get('query', '').strip()

    if not q:
        return jsonify({"status":"error","message":"Empty query"})

    search = f"%{q.lower()}%"

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT student_id, name, bus_id, fee_paid, parent_contact, branch, semester
        FROM students
        WHERE LOWER(student_id) LIKE %s
           OR LOWER(name) LIKE %s
           OR bus_id LIKE %s
    """, (search, search, search))

    rows = cur.fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "student_id": r[0],
            "name": r[1],
            "bus_id": r[2],
            "fee_paid": r[3],
            "parent_contact": r[4],
            "branch": r[5],
            "semester": r[6]
        })

    return jsonify({"status":"success", "results":results})

# ----------------------------------------------------
# QR VERIFICATION API (Used by Scanner App)
# ----------------------------------------------------
@app.route('/verify_qr', methods=['POST'])
def verify_qr():
    data = request.get_json()
    query = (data.get("student_id") or data.get("query") or "").strip()

    if not query:
        return jsonify({
            "status": "Error",
            "message": "No student identifier provided.",
            "student_data": None
        })

    conn = get_db()
    cur = conn.cursor()

    # Base search by student_id (case-insensitive)
    cur.execute("""
        SELECT student_id, name, bus_id, fee_paid, parent_contact,
               semester, branch, amount_paid, transaction_date
        FROM students
        WHERE LOWER(student_id) = LOWER(%s)
    """, (query,))
    row = cur.fetchone()

    # If no direct match, try bus_id or name search
    if not row:
        search = f"%{query.lower()}%"

        if query.isdigit():  # search by exact bus number
            cur.execute("""
                SELECT student_id, name, bus_id, fee_paid, parent_contact,
                       semester, branch, amount_paid, transaction_date
                FROM students
                WHERE bus_id = %s
            """, (query,))
            rows = cur.fetchall()
        else:
            cur.execute("""
                SELECT student_id, name, bus_id, fee_paid, parent_contact,
                       semester, branch, amount_paid, transaction_date
                FROM students
                WHERE LOWER(name) LIKE %s
            """, (search,))
            rows = cur.fetchall()

        # No match
        if not rows:
            conn.close()
            return jsonify({
                "status": "Error",
                "message": "Student not found!",
                "student_data": None
            })

        # Multiple matches
        if len(rows) > 1:
            matches = [{"student_id": r[0], "name": r[1], "bus_id": r[2]} for r in rows[:5]]
            conn.close()
            return jsonify({
                "status": "Multiple",
                "message": "Multiple students matched. Select correct Student ID.",
                "matches": matches,
                "student_data": None
            })

        # Single match
        row = rows[0]

    student_id_db, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date = row

    # Fetch extra fields (photo, qr url)
    cur.execute("""
        SELECT email, photo_filename, qr_url
        FROM students
        WHERE student_id = %s
    """, (student_id_db,))
    ext = cur.fetchone()
    email, photo_file, qr_url = ext if ext else ("", None, "")

    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")

    student_data = {
        "student_id": student_id_db,
        "name": name,
        "bus_id": bus_id,
        "fee_paid": fee_paid,
        "parent_contact": format_phone_display(parent_contact),
        "semester": semester or "N/A",
        "branch": branch or "N/A",
        "amount_paid": amount_paid,
        "transaction_date": format_date(transaction_date) if transaction_date else None,
        "email": email,
        "photo_url": url_for('static', filename=f"student_photos/{photo_file}") if photo_file else None,
        "qr_url": qr_url
    }

    # Check today's scan log
    cur.execute("""
        SELECT 1 FROM scan_log
        WHERE student_id = %s AND scan_date = %s
    """, (student_id_db, today))
    already = cur.fetchone()

    if already:
        conn.close()
        return jsonify({
            "status": "duplicate",
            "message": "Duplicate Scan Detected — Already scanned today.",
            "student_data": student_data,
            "duplicate": True
        })

    # Insert scan log entry
    cur.execute("""
        INSERT INTO scan_log (student_id, scan_date, scan_time)
        VALUES (%s, %s, %s)
    """, (student_id_db, today, current_time))
    conn.commit()
    conn.close()

    # Build message
    if fee_paid == 1:
        if amount_paid:
            msg = f"Access Granted — {name} has paid ₹{amount_paid:,}."
        else:
            msg = f"Access Granted — {name} has paid."
    else:
        msg = f"Access Denied — {name} has NOT paid."

    return jsonify({
        "status": "success",
        "message": msg,
        "student_data": student_data,
        "duplicate": False
    })


# ----------------------------------------------------
# EXPORT EXCEL (PostgreSQL)
# ----------------------------------------------------
@app.route('/export_excel')
def export_excel():
    if 'admin' not in session:
        return redirect(url_for('admin_page'))

    try:
        import pandas as pd
        from io import BytesIO

        conn = get_db()
        df = pd.read_sql("SELECT * FROM students", conn)
        conn.close()

        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Students')
        output.seek(0)

        return send_file(
            output,
            download_name="students_report.xlsx",
            as_attachment=True,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        flash(f"Export failed: {e}")
        return redirect(url_for('admin_dashboard'))


# ----------------------------------------------------
# FINAL RUN BLOCK
# ----------------------------------------------------
if __name__ == '__main__':
    print("GoCampus running with PostgreSQL + Cloudinary")
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv("PORT", 5000)))
 