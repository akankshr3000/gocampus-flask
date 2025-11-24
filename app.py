# app.py
"""
GoCampus Flask app with Cloudinary QR upload integrated.

Requirements:
    pip install Flask segno pillow cloudinary pandas xlsxwriter
(plus other libs you already had)

Before starting, set environment variables:
    CLOUDINARY_URL (recommended) e.g. cloudinary://API_KEY:API_SECRET@CLOUD_NAME
    FLASK_SECRET (for session)
"""

import os
import io
import re
import sqlite3
import traceback
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session,
    jsonify, send_file
)
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
import segno
import cloudinary
import cloudinary.uploader

# ---------- Config ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "students.db")

# Local fallback directories (useful for dev)
QR_PATH = os.path.join(BASE_DIR, "backend_qrcodes")      # local QR backups (optional)
PHOTO_PATH = os.path.join(BASE_DIR, "static", "student_photos")
COLLEGE_LOGO_PRIMARY = os.path.join(BASE_DIR, "static", "college_logo", "bitm_logo.png")
FALLBACK_LOGO_1 = os.path.join(BASE_DIR, "static", "college_logo", "fallback1.png")
FALLBACK_LOGO_2 = os.path.join(BASE_DIR, "static", "college_logo", "fallback2.png")

os.makedirs(QR_PATH, exist_ok=True)
os.makedirs(PHOTO_PATH, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static", "college_logo"), exist_ok=True)

# Cloudinary configuration using CLOUDINARY_URL (recommended)
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")

if CLOUDINARY_URL:
    # cloudinary.config() will pick up CLOUDINARY_URL automatically;
    # we set secure=True explicitly.
    cloudinary.config(secure=True)
    print("Cloudinary configured using CLOUDINARY_URL")
else:
    print("WARNING: CLOUDINARY_URL not found. Cloud uploads disabled.")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev_secret_change_me")  # set a real secret in production

# -----------------------------
# DB helpers & ensure tables
# -----------------------------
def ensure_tables():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # students table (minimal columns) - add any additional columns you already had
    c.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT UNIQUE,
        name TEXT,
        bus_id TEXT,
        fee_paid INTEGER DEFAULT 0,
        parent_contact TEXT,
        semester TEXT,
        branch TEXT,
        amount_paid INTEGER,
        transaction_date TEXT,
        email TEXT,
        photo_filename TEXT,
        registration_date TEXT,
        valid_till TEXT,
        current_sem INTEGER,
        is_active_transport INTEGER DEFAULT 0,
        qr_url TEXT
    )
    """)
    # scan_log
    c.execute("""
    CREATE TABLE IF NOT EXISTS scan_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        scan_date TEXT NOT NULL,
        scan_time TEXT NOT NULL
    )
    """)
    # index for scan_log
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_scan_log_student_date ON scan_log (student_id, scan_date)
    """)
    # help_tickets
    c.execute("""
    CREATE TABLE IF NOT EXISTS help_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        usn TEXT NOT NULL,
        email TEXT NOT NULL,
        issue TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        status TEXT DEFAULT 'Open',
        resolved_at TEXT
    )
    """)
    # renewal_history (optional)
    c.execute("""
    CREATE TABLE IF NOT EXISTS renewal_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        renewed_date TEXT,
        previous_valid_till TEXT,
        new_valid_till TEXT
    )
    """)
    conn.commit()
    conn.close()

ensure_tables()

# -----------------------------
# Utility helpers
# -----------------------------
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
        return True, ""  # Optional
    if len(digits) != 10:
        return False, "Phone number must be exactly 10 digits"
    if len(set(digits)) == 1:
        return False, "Phone number cannot use the same digit repeated 10 times"
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

def validate_photo(file_stream):
    file_stream.seek(0, os.SEEK_END)
    size = file_stream.tell()
    file_stream.seek(0)
    if size > 3 * 1024 * 1024:
        return False, "File size exceeds 3MB limit."
    try:
        img = Image.open(file_stream)
        img.verify()
        file_stream.seek(0)
        img = Image.open(file_stream)
        if img.format not in ['JPEG', 'PNG']:
            return False, "Only JPG and PNG formats are allowed."
        width, height = img.size
        if width < 300 or height < 300:
            return False, "Image resolution must be at least 300x300 pixels."
        aspect_ratio = width / height
        if not (0.6 <= aspect_ratio <= 1.4):
            return False, "Image must be a portrait or square (passport style)."
        gray = img.convert('L')
        hist = gray.histogram()
        total_pixels = width * height
        dark_pixels = sum(hist[:30])
        bright_pixels = sum(hist[225:])
        if (dark_pixels + bright_pixels) / total_pixels > 0.40:
            return False, "Image looks like a QR code or document (too much high contrast). Please upload a proper photo."
        return True, ""
    except Exception as e:
        return False, f"Invalid image file: {str(e)}"

def generate_student_id():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT MAX(CAST(SUBSTR(student_id, 2) AS INTEGER)) FROM students")
    result = c.fetchone()
    conn.close()

    last_num = result[0] if result and result[0] is not None else 0
    next_num = last_num + 1

    return f"S{next_num:02d}"

 
# -----------------------------
# QR generation & upload
# -----------------------------
def generate_secure_qr(student_id: str):
    """
    Generate a high-quality QR image and upload to Cloudinary.
    Returns the secure_url from Cloudinary (or local file path if Cloudinary not configured).
    """
    try:
        # Base QR with segno (ECC high)
        qr = segno.make(student_id, error='h')
        # Produce an in-memory PNG
        qr_buffer = io.BytesIO()
        # Save base QR to a PNG (scale large for high-res)
        qr.save(qr_buffer, kind='png', scale=20, border=4)
        qr_buffer.seek(0)
        qr_img = Image.open(qr_buffer).convert("RGBA")

        # Resize to square target
        target_size = 1500
        qr_img = qr_img.resize((target_size, target_size), resample=Image.NEAREST)

        # final canvas (white BG)
        final = Image.new("RGBA", qr_img.size, (255, 255, 255, 255))

        # watermark tile behind QR
        watermark_text = "Ballari Institute of Technology and Management"
        try:
            font = ImageFont.truetype("arial.ttf", 35)
            font_small = ImageFont.truetype("arial.ttf", 20)
        except Exception:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()

        watermark_layer = Image.new("RGBA", final.size, (255,255,255,0))
        opacity = int(255 * 0.08)  # ~8%

        tmp = Image.new("RGBA", (final.width, 100), (255,255,255,0))
        tmp_draw = ImageDraw.Draw(tmp)
        bbox = tmp_draw.textbbox((0,0), watermark_text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tmp_draw.text(((final.width - text_w)//2, (100 - text_h)//2), watermark_text, fill=(0,0,0,opacity), font=font)
        rotated = tmp.rotate(30, expand=1)

        for y in range(-rotated.height, final.height + rotated.height, rotated.height + 120):
            for x in range(-rotated.width, final.width + rotated.width, rotated.width + 120):
                watermark_layer.paste(rotated, (x,y), rotated)

        final = Image.alpha_composite(final, watermark_layer)

        # paste QR on top
        qr_rgb = qr_img.convert("RGB")
        final_rgb = final.convert("RGB")
        final_rgb.paste(qr_rgb, (0,0))
        final = final_rgb.convert("RGBA")

        # center logo if exists
        logo_candidates = [COLLEGE_LOGO_PRIMARY, FALLBACK_LOGO_1, FALLBACK_LOGO_2]
        logo_path = next((p for p in logo_candidates if os.path.exists(p)), None)
        if logo_path:
            try:
                logo = Image.open(logo_path).convert("RGBA")
                lw, lh = logo.size
                if lw != lh:
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
                bg_draw.rounded_rectangle((0,0,bg_size[0],bg_size[1]), radius=radius, fill=(255,255,255,255))
                bg_pos = ((final.width - bg_size[0])//2, (final.height - bg_size[1])//2)
                logo_pos = (bg_pos[0] + pad, bg_pos[1] + pad)
                final.paste(bg, bg_pos, bg)
                final.paste(logo, logo_pos, logo)
            except Exception:
                pass

        # micro-text border
        border_draw = ImageDraw.Draw(final)
        border_text = "BITM • " * 50
        border_offset = 50
        border_draw.text((border_offset, 10), border_text, font=font_small, fill=(0,0,0,255))
        bbox_b = border_draw.textbbox((0,0), border_text, font=font_small)
        h_text = bbox_b[3] - bbox_b[1]
        border_draw.text((border_offset, final.height - h_text - 10), border_text, font=font_small, fill=(0,0,0,255))
        side_strip = Image.new("RGBA", (final.height, 40), (255,255,255,0))
        sdraw = ImageDraw.Draw(side_strip)
        sdraw.text((border_offset, 5), border_text, font=font_small, fill=(0,0,0,255))
        left_side = side_strip.rotate(90, expand=True)
        right_side = side_strip.rotate(-90, expand=True)
        final.paste(left_side, (10,0), left_side)
        final.paste(right_side, (final.width - right_side.width - 10, 0), right_side)

        # Save final to memory
        mem = io.BytesIO()
        final.save(mem, format="PNG")
        mem.seek(0)

               # Upload to Cloudinary using CLOUDINARY_URL
        if CLOUDINARY_URL:
            try:
                upload_result = cloudinary.uploader.upload(
                    mem,
                    folder="gocampus_qr",
                    public_id=student_id,
                    overwrite=True,
                    resource_type="image"
                )
                print("CLOUDINARY UPLOAD RESULT:", upload_result)   # DEBUG
                qr_url = upload_result.get("secure_url")

                # Save backup to local (optional)
                try:
                    local_path = os.path.join(QR_PATH, f"{student_id}.png")
                    final.save(local_path, format="PNG")
                except:
                    pass

                return qr_url

            except Exception as e:
                print("Cloudinary upload failed:", repr(e))  # DEBUG
                local_path = os.path.join(QR_PATH, f"{student_id}.png")
                final.save(local_path, format="PNG")
                return local_path
        else:
            local_path = os.path.join(QR_PATH, f"{student_id}.png")
            final.save(local_path, format="PNG")
            return local_path 

    except Exception as e:
        traceback.print_exc()
        raise  

# -----------------------------
# Routes (main)
# -----------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/verify', methods=['GET'])
def verify_page():
    return render_template('verify_qr_public.html')

@app.route('/verify', methods=['POST'])
def verify():
    student_id = request.form.get('student_id')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, fee_paid FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return render_template('result.html', message="Student not found ❌", color="red")
    name, paid = row
    c.execute("SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date, email, photo_filename, qr_url FROM students WHERE student_id=?", (student_id,))
    full_row = c.fetchone()
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
        return render_template('result.html', message=f"✅ Access Granted — {name} has paid.", color="green", student=student)
    else:
        return render_template('result.html', message=f"🚫 Access Denied — {name} has NOT paid.", color="red", student=student)

# Admin pages
@app.route('/admin', methods=['GET'])
def admin_page():
    return render_template('admin_login.html')

@app.route('/admin_login', methods=['POST'])
def admin_login():
    username = request.form.get('username')
    password = request.form.get('password')
    # simple auth for demo - change for production
    if username == "admin" and password == "12345":
        session['admin'] = username
        return redirect(url_for('admin_dashboard'))
    flash("Invalid credentials ❌")
    return redirect(url_for('admin_page'))

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("DELETE FROM help_tickets WHERE status='Resolved' AND resolved_at <= datetime('now', '-5 days')")
        conn.commit()
    except Exception:
        pass
    c.execute("SELECT id, student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date, email, photo_filename, valid_till, current_sem, qr_url FROM students ORDER BY student_id")
    rows = c.fetchall()
    conn.close()
    students = []
    renewal_alerts = []
    for r in rows:
        r = list(r)
        r[5] = format_phone_display(r[5])
        students.append(tuple(r))
        valid_till = r[11]
        needs_renewal = False
        is_expired = False
        if valid_till:
            try:
                dt = datetime.strptime(valid_till, "%Y-%m-%d")
                days_left = (dt - datetime.now()).days
                if days_left <= 30:
                    needs_renewal = True
                    is_expired = days_left < 0
            except:
                pass
        if needs_renewal:
            renewal_alerts.append({
                'student_id': r[1],
                'name': r[2],
                'valid_till': format_date(valid_till),
                'is_expired': is_expired
            })
    paid_count = sum(1 for s in students if s[4] == 1)
    unpaid_count = sum(1 for s in students if s[4] == 0)
    chart_data = {'paid': paid_count, 'unpaid': unpaid_count, 'total': paid_count + unpaid_count}
    return render_template('admin_dashboard.html', students=students, chart_data=chart_data, renewal_alerts=renewal_alerts)

# Add student route - receives photo upload
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
    branch_normalized = branch.lower() if branch else ''
    semester_value = semester.strip()

    errors = []
    if not name:
        errors.append("Name is required")
    bus_valid, bus_error = validate_bus_id(bus_id)
    if not bus_valid:
        errors.append(bus_error)
    phone_valid, phone_error = validate_phone(parent_contact_raw)
    if not phone_valid:
        errors.append(phone_error)

    photo_file = request.files.get('photo')
    photo_filename = None
    if not photo_file or photo_file.filename == '':
        errors.append("Student photo is required")
    else:
        is_valid_photo, photo_msg = validate_photo(photo_file)
        if not is_valid_photo:
            errors.append(photo_msg)
        else:
            ext = os.path.splitext(photo_file.filename)[1].lower()
            # sanitize filename
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

    phone_digits = normalize_phone(parent_contact_raw)
    parent_contact_db = f"+91{phone_digits}" if phone_digits else None

    try:
        fee_val = 1 if fee_paid == '1' else 0
    except:
        fee_val = 0

    amount_paid = None
    transaction_date = None
    if fee_val == 1:
        amount_paid_input = request.form.get('amount_paid', '').strip().replace(',', '')
        try:
            amount_val = int(amount_paid_input)
        except:
            amount_val = None
        if amount_val != 15000:
            flash("Amount must be exactly ₹15000 for Paid status.")
            return redirect(url_for('admin_dashboard'))
        amount_paid = 15000
        transaction_date = datetime.now().strftime("%Y-%m-%d")

    registration_date = datetime.now().strftime("%Y-%m-%d")
    valid_till = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    current_sem = int(semester_value) if semester_value and semester_value.isdigit() else 1
    is_active_transport = 1

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # simple duplicates checks
        if parent_contact_db:
            c.execute("SELECT COUNT(*) FROM students WHERE LOWER(name)=? AND parent_contact=?", (name.lower(), parent_contact_db))
            if c.fetchone()[0] > 0:
                conn.close()
                flash("A student with the same name and phone number already exists.")
                return redirect(url_for('admin_dashboard'))

        c.execute("""INSERT INTO students (student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date, email, photo_filename, registration_date, valid_till, current_sem, is_active_transport)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (student_id, name, bus_id, fee_val, parent_contact_db, semester_value, branch, amount_paid, transaction_date, email, photo_filename, registration_date, valid_till, current_sem, is_active_transport))
        conn.commit()

        # After commit, generate QR and upload
        try:
            qr_result = generate_secure_qr(student_id)
            # qr_result may be a secure cloud URL or local path
            # save qr_url into DB column 'qr_url'
            c.execute("UPDATE students SET qr_url=? WHERE student_id=?", (qr_result, student_id))
            conn.commit()
        except Exception as qr_err:
            # QR generation/upload failed but student still added - inform admin
            flash(f"Student {name} ({student_id}) added but QR failed: {qr_err}")
            conn.close()
            return redirect(url_for('admin_dashboard'))

        conn.close()
    except sqlite3.IntegrityError:
        flash(f"Student ID {student_id} already exists!")
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        flash("Error adding student: " + str(e))
        return redirect(url_for('admin_dashboard'))

    flash(f"Student {name} ({student_id}) added successfully! QR generated.")
    return redirect(url_for('admin_dashboard'))

# Generate QR from admin UI for existing student
@app.route('/generate_qr_admin', methods=['POST'])
def generate_qr_admin():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))
    student_id = request.form.get('student_id')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Student ID not found")
        return redirect(url_for('admin_dashboard'))
    try:
        qr_result = generate_secure_qr(student_id)
        c.execute("UPDATE students SET qr_url=? WHERE student_id=?", (qr_result, student_id))
        conn.commit()
        conn.close()
        flash(f"✅ QR generated for {row[0]} ({student_id})")
    except Exception as e:
        conn.close()
        flash(f"QR generation failed: {e}")
    return redirect(url_for('admin_dashboard'))

# Export excel
@app.route('/export_excel')
def export_excel():
    if 'admin' not in session:
        return redirect(url_for('admin_page'))
    try:
        import pandas as pd
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM students", conn)
        conn.close()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Students')
        output.seek(0)
        return send_file(
            output,
            download_name="students_report.xlsx",
            as_attachment=True,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except ImportError:
        flash("Pandas/XlsxWriter not installed. Cannot export.")
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        flash(f"Export failed: {e}")
        return redirect(url_for('admin_dashboard'))

# remaining routes: delete_student, mark_paid_admin, scan, verify_qr, etc.
@app.route('/delete_student', methods=['POST'])
def delete_student():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))
    student_id = request.form.get('student_id')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM students WHERE student_id=?", (student_id,))
    conn.commit()
    conn.close()
    # delete local files if any
    try:
        local_qr = os.path.join(QR_PATH, f"{student_id}.png")
        if os.path.exists(local_qr):
            os.remove(local_qr)
    except:
        pass
    # Attempt: delete Cloudinary image (optional) - requires cloud config
    try:
        if CLOUDINARY_URL:
            cloudinary.uploader.destroy(f"gocampus_qr/{student_id}", resource_type="image")
    except Exception:
        pass
    # delete photo
    for ext in (".jpg", ".jpeg", ".png"):
        p = os.path.join(PHOTO_PATH, f"{student_id}{ext}")
        if os.path.exists(p):
            try:
                os.remove(p)
            except:
                pass
    flash(f"Student {student_id} deleted successfully.")
    return redirect(url_for('admin_dashboard'))

@app.route('/mark_paid_admin', methods=['POST'])
def mark_paid_admin():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))
    student_id = request.form.get('student_id')
    amount_paid = request.form.get('amount_paid', '').strip()
    cleaned = amount_paid.replace(',', '').replace(' ', '')
    transaction_date = datetime.now().strftime("%Y-%m-%d")
    amount = None
    if cleaned:
        try:
            amount = int(cleaned)
        except:
            amount = None
    if amount != 15000:
        flash("Amount must be exactly ₹15000")
        return redirect(url_for('admin_dashboard'))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE students SET fee_paid=1, amount_paid=?, transaction_date=? WHERE student_id=?", (amount, transaction_date, student_id))
    conn.commit()
    conn.close()
    flash(f"{student_id} marked Paid")
    return redirect(url_for('admin_dashboard'))

# small helper routes for phone check / search
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM students WHERE parent_contact=?", (phone_db,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"status":"exists","exists":True,"name":row[0]})
    return jsonify({"status":"ok","exists":False})

@app.route('/search_student', methods=['POST'])
def search_student():
    if 'admin' not in session:
        return jsonify({"error":"Unauthorized"}), 401
    data = request.get_json()
    q = data.get('query','').strip()
    if not q:
        return jsonify({"status":"error","message":"Empty query"})
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT student_id, name, bus_id, fee_paid, parent_contact, branch, semester FROM students WHERE student_id LIKE ? OR name LIKE ? OR bus_id LIKE ?", (f"%{q}%", f"%{q}%", f"%{q}%"))
    rows = c.fetchall()
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
    return jsonify({"status":"success","results":results})

# QR verification API (used by scanner)
@app.route('/verify_qr', methods=['POST'])
def verify_qr():
    data = request.get_json()
    query = (data.get("student_id") or data.get("query") or "").strip()
    if not query:
        return jsonify({"status":"Error","message":"No student identifier provided.","student_data":None})
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    base_query = """SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date FROM students WHERE LOWER(student_id)=LOWER(?)"""
    c.execute(base_query, (query,))
    row = c.fetchone()
    if not row:
        potential_rows = []
        search_term = f"%{query.lower()}%"
        if query.isdigit():
            c.execute("""SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date FROM students WHERE bus_id=?""", (query,))
            potential_rows = c.fetchall()
            if not potential_rows:
                c.execute("""SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date FROM students WHERE bus_id LIKE ?""", (search_term,))
                potential_rows = c.fetchall()
        else:
            c.execute("""SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date FROM students WHERE LOWER(name)=?""", (query.lower(),))
            potential_rows = c.fetchall()
            if not potential_rows:
                c.execute("""SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date FROM students WHERE LOWER(name) LIKE ?""", (search_term,))
                potential_rows = c.fetchall()
        if len(potential_rows) == 1:
            row = potential_rows[0]
        elif len(potential_rows) > 1:
            matches = [{"student_id": r[0], "name": r[1], "bus_id": r[2]} for r in potential_rows[:5]]
            conn.close()
            return jsonify({"status":"Multiple","message":"Multiple students matched this search. Please select the correct Student ID.","matches":matches,"student_data":None})
        else:
            conn.close()
            return jsonify({"status":"Error","message":"Student not found!","student_data":None})

    student_id_db, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date = row
    c.execute("SELECT email, photo_filename, qr_url FROM students WHERE student_id=?", (student_id_db,))
    extra = c.fetchone()
    email = extra[0] if extra else ""
    photo_filename = extra[1] if extra else ""
    qr_url = extra[2] if extra else ""
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")
    phone_display = format_phone_display(parent_contact)
    student_data = {
        "student_id": student_id_db,
        "name": name,
        "bus_id": bus_id,
        "fee_paid": fee_paid,
        "parent_contact": phone_display,
        "phone_display": phone_display,
        "phone_raw": parent_contact,
        "semester": semester or "N/A",
        "branch": branch or "N/A",
        "amount_paid": amount_paid,
        "transaction_date": format_date(transaction_date) if transaction_date else None,
        "email": email,
        "photo_url": url_for('static', filename=f'student_photos/{photo_filename}') if photo_filename else None,
        "qr_url": qr_url
    }
    c.execute("SELECT 1 FROM scan_log WHERE student_id=? AND scan_date=?", (student_id_db, today))
    already_scanned = c.fetchone() is not None
    if already_scanned:
        conn.close()
        return jsonify({"status":"duplicate","message":"Duplicate Scan Detected — Already scanned today.","student_data":student_data,"duplicate":True})
    c.execute("INSERT INTO scan_log (student_id, scan_date, scan_time) VALUES (?, ?, ?)", (student_id_db, today, current_time))
    conn.commit()
    conn.close()
    if fee_paid == 1:
        if amount_paid and transaction_date:
            message = f"Access Granted — {name} has paid ₹{amount_paid:,} on {student_data['transaction_date']}."
        elif transaction_date:
            message = f"Access Granted — {name} has paid on {student_data['transaction_date']}."
        else:
            message = f"Access Granted — {name} has paid."
        return jsonify({"status":"success","message":message,"student_data":student_data,"duplicate":False})
    else:
        return jsonify({"status":"success","message":f"Access Denied — {name} has NOT paid.","student_data":student_data,"duplicate":False})

# -----------------------------
# Run
# -----------------------------
if __name__ == '__main__':
    ensure_tables()
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv("PORT", 5000)))
  