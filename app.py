# app.py (FULL file - replaced QR generation with secure generator)
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
import sqlite3, qrcode, os
from datetime import datetime, timedelta
import re
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
import io
import segno

# -----------------------------
# Constants 
# -----------------------------

# -----------------------------
# Constants
# -----------------------------
DB_PATH = os.path.join(os.getcwd(), "database", "students.db")
QR_PATH = os.path.join(os.getcwd(), "static", "qrcodes")
PHOTO_PATH = os.path.join(os.getcwd(), "static", "student_photos")

COLLEGE_LOGO_PRIMARY = os.path.join("static", "college_logo", "bitm_logo.png")
FALLBACK_LOGO_1 = os.path.join("static", "college_logo", "fallback1.png")
FALLBACK_LOGO_2 = os.path.join("static", "college_logo", "fallback2.png")

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Required for flash messages

# -----------------------------
# Secure QR generation helper
# -----------------------------
def generate_secure_qr(student_id):
    """
    Generate a secure QR with:
      - segno ECC-H
      - center logo with white rounded background (~17% area for better scannability)
      - faint diagonal watermark text (8-12% opacity)
      - micro-text border ("BITM • BITM ...")
      - saves to static/qrcodes/{student_id}.png
    Returns the saved path.
    """
    try:
        # 1) Create base QR (segno) as a temporary PNG
        qr = segno.make(student_id, error='h')
        qr_temp_path = os.path.join(QR_PATH, f"{student_id}_temp.png")
        # Increased border from 2 to 4 for better quiet zone (essential for scanning)
        qr.save(qr_temp_path, scale=20, border=4)  
        
        qr_img = Image.open(qr_temp_path).convert("RGBA")
        # Resize to target 1500x1500 (preserve aspect)
        target_size = 1500
        qr_img = qr_img.resize((target_size, target_size), resample=Image.NEAREST)

        # Create final canvas - keep white background OPAQUE for better scanning
        final = Image.new("RGBA", qr_img.size, (255, 255, 255, 255))
        
        # 2) Draw faint diagonal watermark tiled behind the QR modules
        watermark_text = "Ballari Institute of Technology and Management"
        
        # attempt to load a truetype font; fallback to default
        try:
            font = ImageFont.truetype("arial.ttf", 35)  # Slightly smaller to reduce interference
            font_small = ImageFont.truetype("arial.ttf", 20)  # Smaller border text
        except Exception:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # create a watermark layer so we can composite it below QR modules
        watermark_layer = Image.new("RGBA", final.size, (255,255,255,0))
        
        # diagonal spacing and opacity tuned for printed behaviour
        opacity = int(255 * 0.08)  # Reduced to 8% for less interference
        
        # rotate approach: draw horizontal text on a temporary image then rotate and paste repeatedly
        tmp = Image.new("RGBA", (final.width, 100), (255,255,255,0))
        tmp_draw = ImageDraw.Draw(tmp)
        bbox = tmp_draw.textbbox((0, 0), watermark_text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tmp_draw.text(((final.width - text_w) // 2, (100 - text_h) // 2), watermark_text, fill=(0,0,0,opacity), font=font)
        rotated = tmp.rotate(30, expand=1)

        # tile the rotated watermark across the watermark_layer
        for y in range(-rotated.height, final.height + rotated.height, rotated.height + 120):
            for x in range(-rotated.width, final.width + rotated.width, rotated.width + 120):
                watermark_layer.paste(rotated, (x, y), rotated)

        # Composite watermark directly on white background (no transparency manipulation)
        # This keeps the QR code scannable by maintaining proper contrast
        final = Image.alpha_composite(final, watermark_layer)
        
        # Now paste QR on top - keep it as-is (black on white) for maximum scannability
        # Convert to same mode for pasting
        qr_rgb = qr_img.convert("RGB")
        final_rgb = final.convert("RGB")
        final_rgb.paste(qr_rgb, (0, 0))
        final = final_rgb.convert("RGBA")

        # 3) Paste center logo inside a white rounded-square background
        logo_path_candidates = [COLLEGE_LOGO_PRIMARY, FALLBACK_LOGO_1, FALLBACK_LOGO_2]
        logo_path = None
        for p in logo_path_candidates:
            if os.path.exists(p):
                logo_path = p
                break
 
        if logo_path:
            try:
                logo = Image.open(logo_path).convert("RGBA")
                # ensure logo fits square; create square crop or pad
                lw, lh = logo.size
                # Make logo square by padding
                if lw != lh:
                    s = max(lw, lh)
                    logo_square = Image.new("RGBA", (s, s), (255,255,255,0))
                    logo_square.paste(logo, ((s-lw)//2, (s-lh)//2), logo)
                    logo = logo_square
                
                # REDUCED logo size from 25% to 17% for better scannability
                # Even with ECC-H, 25% was too much coverage
                logo_size = int(final.width * 0.17)
                logo = logo.resize((logo_size, logo_size), resample=Image.LANCZOS)
                
                # make white rounded background slightly larger than logo
                pad = int(logo_size * 0.12) 
                bg_size = (logo_size + pad*2, logo_size + pad*2)
                bg = Image.new("RGBA", bg_size, (255,255,255,255))  # Opaque white
                bg_draw = ImageDraw.Draw(bg)
                radius = int(min(bg_size)//5)
                
                # rounded rectangle
                bg_draw.rounded_rectangle((0,0,bg_size[0],bg_size[1]), radius=radius, fill=(255,255,255,255))
                
                # compute paste positions (center)
                bg_pos = ((final.width - bg_size[0])//2, (final.height - bg_size[1])//2)
                logo_pos = (bg_pos[0] + pad, bg_pos[1] + pad)
                
                # compose - paste background first, then logo
                final.paste(bg, bg_pos, bg)
                final.paste(logo, logo_pos, logo)
            except Exception:
                pass # Fallback to no logo

        # 4) Add micro-text border (crisp in original)
        # Position border text OUTSIDE the QR quiet zone (at least 50px from edge)
        border_draw = ImageDraw.Draw(final)
        border_text = "BITM • " * 50 # Repeat enough
        border_offset = 50  # Keep away from QR quiet zone
        
        # top
        border_draw.text((border_offset, 10), border_text, font=font_small, fill=(0,0,0,255))
        # bottom
        bbox_b = border_draw.textbbox((0,0), border_text, font=font_small)
        h_text = bbox_b[3] - bbox_b[1]
        border_draw.text((border_offset, final.height - h_text - 10), border_text, font=font_small, fill=(0,0,0,255))
        
        # Left and Right needs rotation
        # Create a long strip for side text
        side_strip = Image.new("RGBA", (final.height, 40), (255,255,255,0))
        sdraw = ImageDraw.Draw(side_strip)
        sdraw.text((border_offset, 5), border_text, font=font_small, fill=(0,0,0,255))
        
        # Rotate 90 for left
        left_side = side_strip.rotate(90, expand=True)
        final.paste(left_side, (10, 0), left_side)
        
        # Rotate -90 (or 270) for right
        right_side = side_strip.rotate(-90, expand=True)
        final.paste(right_side, (final.width - right_side.width - 10, 0), right_side)

        # final save as PNG
        final_path = os.path.join(QR_PATH, f"{student_id}.png")
        final.save(final_path, format="PNG")

        # cleanup temp if exists
        try:
            if os.path.exists(qr_temp_path):
                os.remove(qr_temp_path)
        except Exception:
            pass

        return final_path
    except Exception as e:
        # bubble up error
        raise


# -----------------------------
# Ensure required DB tables
# -----------------------------
def ensure_scan_log_table():
    """Create scan_log table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            scan_date TEXT NOT NULL,
            scan_time TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_log_student_date
        ON scan_log (student_id, scan_date)
    """)
    conn.commit()
    conn.close()

def ensure_help_tickets_table():
    """Create help_tickets table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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
    # Migration: Add resolved_at if it doesn't exist
    try:
        c.execute("ALTER TABLE help_tickets ADD COLUMN resolved_at TEXT")
    except sqlite3.OperationalError:
        pass # Column likely already exists
    try:
        c.execute("ALTER TABLE help_tickets ADD COLUMN status TEXT DEFAULT 'Open'")
    except sqlite3.OperationalError:
        pass # Column likely already exists
    conn.commit()
    conn.close()

ensure_scan_log_table()
ensure_help_tickets_table()

# -----------------------------
# Utility Helpers (unchanged)
# -----------------------------
def normalize_phone(phone: str) -> str:
    """Extract numeric digits and keep the last 10 digits (Indian mobile)."""
    if not phone:
        return ""
    digits = re.sub(r'\D', '', phone)
    if len(digits) > 10:
        digits = digits[-10:]
    return digits

def format_phone_display(phone: str) -> str:
    """Return phone in '+91 12345 67890' format when possible."""
    digits = normalize_phone(phone)
    if len(digits) == 10:
        return f"+91 {digits[:5]} {digits[5:]}"
    if phone and phone.startswith("+91") and len(phone) > 3:
        digits = normalize_phone(phone[3:])
        if len(digits) == 10:
            return f"+91 {digits[:5]} {digits[5:]}"
    return phone or ""

def delete_qr_file(student_id: str):
    """Delete the generated QR image file for a student, if it exists."""
    try:
        qr_path = os.path.join(QR_PATH, f"{student_id}.png")
        if os.path.exists(qr_path):
            os.remove(qr_path)
            return True, None
        return False, "QR file not found"
    except Exception as e:
        return False, f"Could not delete QR file: {str(e)}"

def generate_student_id():
    """Auto-generate Student ID in format S01, S02, S03, etc."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT student_id FROM students ORDER BY student_id")
    existing_ids = c.fetchall()
    conn.close()
    used_numbers = set()
    for (sid,) in existing_ids:
        if sid and sid.startswith('S'):
            try:
                num = int(sid[1:])
                used_numbers.add(num)
            except ValueError:
                continue
    next_num = 1
    while next_num in used_numbers:
        next_num += 1
    return f"S{next_num:02d}"

def validate_bus_id(bus_id):
    if not bus_id:
        return False, "Bus No is required"
    if not bus_id.isdigit():
        return False, "Bus No must contain only digits"
    return True, ""

def validate_phone(phone):
    digits = normalize_phone(phone)
    if not digits:
        return True, ""  # Optional field
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

def check_renewal_status(valid_till_str):
    if not valid_till_str:
        return False, False
    try:
        valid_till = datetime.strptime(valid_till_str, "%Y-%m-%d")
        today = datetime.now()
        days_left = (valid_till - today).days
        if days_left <= 30:
            return True, days_left < 0
        return False, False
    except:
        return False, False

# Jinja2 filter
def format_date_filter(date_str):
    return format_date(date_str)
app.jinja_env.filters['format_date'] = format_date_filter

# -----------------------------
# Main Routes (Student Side)
# -----------------------------
@app.route('/')
def index():
    return render_template('index.html')

# Generate QR (public)
@app.route('/generate_qr', methods=['POST'])
def generate_qr():
    student_id = request.form['student_id']
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash("❌ Student ID not found!")
        return redirect(url_for('index'))
    try:
        generate_secure_qr(student_id)
    except Exception as e:
        flash(f"QR generation failed: {str(e)}")
        return redirect(url_for('index'))
    flash(f"✅ QR code generated for {row[0]}")
    return redirect(url_for('index'))

# Verify Fee (GET)
@app.route('/verify', methods=['GET'])
def verify_page():
    return render_template('verify_qr_public.html')

# Verify Fee (POST)
@app.route('/verify', methods=['POST'])
def verify():
    student_id = request.form['student_id']
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, fee_paid FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return render_template('result.html', message="Student not found ❌", color="red")
    name, paid = row
    c.execute("SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date, email, photo_filename FROM students WHERE student_id=?", (student_id,))
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
            'photo_url': url_for('static', filename=f'student_photos/{full_row[10]}') if full_row[10] else None
        }
    if paid:
        return render_template('result.html', message=f"✅ Access Granted — {name} has paid.", color="green", student=student)
    else:
        return render_template('result.html', message=f"🚫 Access Denied — {name} has NOT paid.", color="red", student=student)

# Mark Paid (User Side)
@app.route('/mark_paid', methods=['POST'])
def mark_paid():
    student_id = request.form['student_id']
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE students SET fee_paid=1 WHERE student_id=?", (student_id,))
    conn.commit()
    conn.close()
    flash(f"✅ Student {student_id} marked as Paid")
    return redirect(url_for('index'))

# ------------------------------------------------
#                 ADMIN SECTION
# ------------------------------------------------
@app.route('/admin', methods=['GET'])
def admin_page():
    return render_template('admin_login.html')

@app.route('/admin_login', methods=['POST'])
def admin_login():
    username = request.form['username']
    password = request.form['password']
    if username == "admin" and password == "12345":
        session['admin'] = username
        return redirect(url_for('admin_dashboard'))
    else:
        flash("Invalid credentials ❌")
        return redirect(url_for('admin_page'))

# Add Student (Admin)
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
            photo_filename = f"{student_id}{ext}"
            photo_path = os.path.join(PHOTO_PATH, photo_filename)
            photo_file.seek(0)
            photo_file.save(photo_path)
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
            amount_paid_val = int(amount_paid_input)
        except:
            amount_paid_val = None
        if amount_paid_val != 15000:
            flash("Amount must be exactly ₹15000 for Paid status.", "danger")
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
        duplicate_message = None
        if parent_contact_db:
            c.execute("""SELECT COUNT(*) FROM students 
                         WHERE LOWER(name)=? AND parent_contact=?""",
                      (name.lower(), parent_contact_db))
            if c.fetchone()[0] > 0:
                duplicate_message = "A student with the same name and phone number already exists."
        if not duplicate_message:
            c.execute("""SELECT COUNT(*) FROM students
                         WHERE LOWER(name)=? AND bus_id=? 
                           AND LOWER(COALESCE(branch, ''))=? 
                           AND COALESCE(semester, '')=?""",
                      (name.lower(), bus_id, branch_normalized, semester_value))
            if c.fetchone()[0] > 0:
                duplicate_message = "A student with the same name, bus number, branch, and semester already exists."
        if duplicate_message:
            conn.close()
            flash(duplicate_message)
            return redirect(url_for('admin_dashboard'))
        c.execute("""INSERT INTO students (student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date, email, photo_filename, registration_date, valid_till, current_sem, is_active_transport)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (student_id, name, bus_id, fee_val, parent_contact_db, semester_value, branch, amount_paid, transaction_date, email, photo_filename, registration_date, valid_till, current_sem, is_active_transport))
        conn.commit()
        conn.close()
        # Automatically generate secure QR code for the new student
        try:
            generate_secure_qr(student_id)
        except Exception as qr_error:
            flash(f"Student {name} ({student_id}) added successfully! (QR code generation failed: {str(qr_error)})")
            return redirect(url_for('admin_dashboard'))
    except sqlite3.IntegrityError:
        flash(f"Student ID {student_id} already exists!")
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        flash("Error adding student: " + str(e))
        return redirect(url_for('admin_dashboard'))
    flash(f"Student {name} ({student_id}) added successfully! QR code generated.")
    return redirect(url_for('admin_dashboard'))

# Admin Dashboard
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
    c.execute("""SELECT id, student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date, email, photo_filename, valid_till, current_sem 
                 FROM students ORDER BY student_id""")
    raw_students = c.fetchall()
    students = []
    renewal_alerts = []
    for row in raw_students:
        as_list = list(row)
        as_list[5] = format_phone_display(as_list[5])
        students.append(tuple(as_list))
        valid_till = as_list[12]
        needs_renewal, is_expired = check_renewal_status(valid_till)
        if needs_renewal:
            renewal_alerts.append({
                'student_id': as_list[1],
                'name': as_list[2],
                'valid_till': format_date(valid_till),
                'is_expired': is_expired
            })
    c.execute("SELECT COUNT(*) FROM students WHERE fee_paid = 1")
    paid_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM students WHERE fee_paid = 0")
    unpaid_count = c.fetchone()[0]
    conn.close()
    chart_data = {
        'paid': paid_count,
        'unpaid': unpaid_count,
        'total': paid_count + unpaid_count
    }
    return render_template('admin_dashboard.html', students=students, chart_data=chart_data, renewal_alerts=renewal_alerts)

# Mark Paid (Admin)
@app.route('/mark_paid_admin', methods=['POST'])
def mark_paid_admin():
    if 'admin' not in session:
        return redirect(url_for('admin_page'))
    student_id = request.form['student_id']
    amount_paid = request.form.get('amount_paid', '').strip()
    cleaned = amount_paid.replace(',', '').replace(' ', '')
    transaction_date = datetime.now().strftime("%Y-%m-%d")
    amount = None
    if cleaned:
        try:
            amount = int(cleaned)
        except ValueError:
            amount = None
    if amount != 15000:
        flash("Amount must be exactly ₹15000")
        return redirect(url_for('admin_dashboard'))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if amount:
        c.execute("UPDATE students SET fee_paid=1, amount_paid=?, transaction_date=? WHERE student_id=?", 
                  (amount, transaction_date, student_id))
        flash(f"{student_id} marked as Paid - ₹{amount:,} on {format_date(transaction_date)}")
    else:
        c.execute("UPDATE students SET fee_paid=1, transaction_date=? WHERE student_id=?", 
                  (transaction_date, student_id))
        flash(f"{student_id} marked as Paid on {format_date(transaction_date)}")
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/logout')
def logout():
    session.pop('admin', None)
    flash("Logged out successfully")
    return redirect(url_for('admin_page'))

# QR Scanner Page
@app.route('/scan_qr')
def scan_qr():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))
    return render_template('scan_qr.html')

# Verify QR Data (Public Access)
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    base_query = """SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date 
                    FROM students WHERE LOWER(student_id)=LOWER(?)"""
    c.execute(base_query, (query,))
    row = c.fetchone()
    if not row:
        potential_rows = []
        search_term = f"%{query.lower()}%"
        if query.isdigit():
            c.execute("""SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date
                         FROM students WHERE bus_id=?""", (query,))
            potential_rows = c.fetchall()
            if not potential_rows:
                c.execute("""SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date
                             FROM students WHERE bus_id LIKE ?""", (search_term,))
                potential_rows = c.fetchall()
        else:
            c.execute("""SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date
                         FROM students WHERE LOWER(name)=?""", (query.lower(),))
            potential_rows = c.fetchall()
            if len(potential_rows) == 0:
                c.execute("""SELECT student_id, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date
                             FROM students WHERE LOWER(name) LIKE ?""", (search_term,))
                potential_rows = c.fetchall()
        if len(potential_rows) == 1:
            row = potential_rows[0]
        elif len(potential_rows) > 1:
            matches = [{
                "student_id": r[0],
                "name": r[1],
                "bus_id": r[2]
            } for r in potential_rows[:5]]
            conn.close()
            return jsonify({
                "status": "Multiple",
                "message": "Multiple students matched this search. Please select the correct Student ID.",
                "matches": matches,
                "student_data": None
            })
        else:
            conn.close()
            return jsonify({
                "status": "Error", 
                "message": "Student not found!",
                "student_data": None
            })
    student_id_db, name, bus_id, fee_paid, parent_contact, semester, branch, amount_paid, transaction_date = row
    c.execute("SELECT email, photo_filename FROM students WHERE student_id=?", (student_id_db,))
    extra_row = c.fetchone()
    email = extra_row[0] if extra_row else ""
    photo_filename = extra_row[1] if extra_row else ""
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
        "photo_url": url_for('static', filename=f'student_photos/{photo_filename}') if photo_filename else None
    }
    # Prevent duplicate scans on the same day
    c.execute("SELECT 1 FROM scan_log WHERE student_id=? AND scan_date=?", (student_id_db, today))
    already_scanned = c.fetchone() is not None
    if already_scanned:
        conn.close()
        return jsonify({
            "status": "duplicate",
            "message": "Duplicate Scan Detected — Already scanned today.",
            "student_data": student_data,
            "duplicate": True
        })
    # Record scan attempt
    c.execute(
        "INSERT INTO scan_log (student_id, scan_date, scan_time) VALUES (?, ?, ?)",
        (student_id_db, today, current_time)
    )
    conn.commit()
    conn.close()
    if fee_paid == 1:
        if amount_paid and transaction_date:
            message = f"Access Granted — {name} has paid ₹{amount_paid:,} on {student_data['transaction_date']}."
        elif transaction_date:
            message = f"Access Granted — {name} has paid on {student_data['transaction_date']}."
        else:
            message = f"Access Granted — {name} has paid."
        return jsonify({
            "status": "success", 
            "message": message,
            "student_data": student_data,
            "duplicate": False
        })
    else:
        return jsonify({
            "status": "success", 
            "message": f"Access Denied — {name} has NOT paid.",
            "student_data": student_data,
            "duplicate": False
        })

# Generate QR (Admin Dashboard version)
@app.route('/generate_qr_admin', methods=['POST'])
def generate_qr_admin():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))
    student_id = request.form['student_id']
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash("❌ Student ID not found!")
        return redirect(url_for('admin_dashboard'))
    try:
        generate_secure_qr(student_id)
    except Exception as e:
        flash(f"QR generation failed: {str(e)}")
        return redirect(url_for('admin_dashboard'))
    flash(f"✅ QR generated for {row[0]} ({student_id})")
    return redirect(url_for('admin_dashboard'))

# -----------------------------
# Restored Routes
# -----------------------------

@app.route('/check_phone', methods=['POST'])
def check_phone():
    """Check if a phone number already exists in the database."""
    if 'admin' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    phone_raw = data.get('phone', '').strip()
    
    if not phone_raw:
        return jsonify({"status": "ok", "exists": False})
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    phone_digits = normalize_phone(phone_raw)
    if not phone_digits:
         conn.close()
         return jsonify({"status": "ok", "exists": False})
         
    phone_db = f"+91{phone_digits}"
    
    c.execute("SELECT name FROM students WHERE parent_contact=?", (phone_db,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return jsonify({"status": "exists", "exists": True, "name": row[0]})
    else:
        return jsonify({"status": "ok", "exists": False})

@app.route('/search_student', methods=['POST'])
def search_student():
    if 'admin' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    query = data.get('query', '').strip()
    if not query:
        return jsonify({"status": "error", "message": "Empty query"})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Search by ID, Name, or Bus
    c.execute("SELECT student_id, name, bus_id, fee_paid, parent_contact, branch, semester FROM students WHERE student_id LIKE ? OR name LIKE ? OR bus_id LIKE ?", 
              (f"%{query}%", f"%{query}%", f"%{query}%"))
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
    return jsonify({"status": "success", "results": results})

@app.route('/delete_student', methods=['POST'])
def delete_student():
    if 'admin' not in session:
        flash("Please login first")
        return redirect(url_for('admin_page'))
    
    student_id = request.form['student_id']
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM students WHERE student_id=?", (student_id,))
    conn.commit()
    conn.close()
    
    # Delete QR and Photo
    delete_qr_file(student_id)
    photo_path = os.path.join(PHOTO_PATH, f"{student_id}.jpg") # Try jpg
    if not os.path.exists(photo_path):
        photo_path = os.path.join(PHOTO_PATH, f"{student_id}.png") # Try png
    if os.path.exists(photo_path):
        os.remove(photo_path)

    flash(f"Student {student_id} deleted successfully.")
    return redirect(url_for('admin_dashboard'))

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
        
        return flask.send_file(output, download_name="students_report.xlsx", as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except ImportError:
        flash("Pandas/XlsxWriter not installed. Cannot export.")
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        flash(f"Export failed: {e}")
        return redirect(url_for('admin_dashboard'))

@app.route('/student_issue', methods=['GET', 'POST'])
def student_issue():
    if request.method == 'POST':
        name = request.form.get('name')
        usn = request.form.get('usn')
        email = request.form.get('email', '')
        issue = request.form.get('issue')
        
        if name and usn and issue:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO help_tickets (name, usn, email, issue, timestamp) VALUES (?, ?, ?, ?, ?)",
                      (name, usn, email, issue, timestamp))
            conn.commit()
            conn.close()
            flash("Ticket submitted successfully!", "success")
        else:
            flash("Please fill all fields.", "danger")
        return redirect(url_for('student_issue'))
    return render_template('student_issue.html')

@app.route('/help_tickets')
def help_tickets():
    if 'admin' not in session:
        return redirect(url_for('admin_page'))
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM help_tickets ORDER BY timestamp DESC")
    tickets = c.fetchall()
    conn.close()
    
    return render_template('help_tickets.html', tickets=tickets)

@app.route('/resolve_ticket/<int:ticket_id>', methods=['POST'])
def resolve_ticket(ticket_id):
    if 'admin' not in session:
        return redirect(url_for('admin_page'))
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE help_tickets SET status='Resolved', resolved_at=? WHERE id=?", (resolved_at, ticket_id))
    conn.commit()
    conn.close()
    
    flash("Ticket resolved.")
    return redirect(url_for('admin_dashboard')) # Or help_tickets

@app.route('/renew_transport', methods=['POST'])
def renew_transport():
    if 'admin' not in session:
        return redirect(url_for('admin_page'))
    
    student_id = request.form['student_id']
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT valid_till FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    if row:
        current_valid = row[0]
        # Extend by 1 year
        try:
            curr_date = datetime.strptime(current_valid, "%Y-%m-%d")
            new_date = curr_date + timedelta(days=365)
        except:
            new_date = datetime.now() + timedelta(days=365)
            
        new_valid = new_date.strftime("%Y-%m-%d")
        
        c.execute("UPDATE students SET valid_till=? WHERE student_id=?", (new_valid, student_id))
        
        # Log history
        renewed_date = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO renewal_history (student_id, renewed_date, previous_valid_till, new_valid_till) VALUES (?, ?, ?, ?)",
                  (student_id, renewed_date, current_valid, new_valid))
        conn.commit()
        flash(f"Transport renewed for {student_id} until {format_date(new_valid)}")
    else:
        flash("Student not found")
        
    conn.close()
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    ensure_scan_log_table()
    ensure_help_tickets_table()
    app.run(debug=True, host='0.0.0.0', port=5000)
