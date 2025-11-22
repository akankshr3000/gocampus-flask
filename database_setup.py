import sqlite3, os

# --- Absolute database path ---
db_dir = os.path.join(os.getcwd(), "database")
os.makedirs(db_dir, exist_ok=True)
db_path = os.path.join(db_dir, "students.db")

print("Database path:", db_path)  # debug print

# --- Connect to SQLite database ---
conn = sqlite3.connect(db_path)
c = conn.cursor()

# --- Create table for students ---
c.execute('''
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT UNIQUE,
    name TEXT,
    bus_id TEXT,
    fee_paid INTEGER DEFAULT 0,
    parent_contact TEXT
)
''')

# --- Insert sample data ---
c.executemany('''
INSERT OR IGNORE INTO students (student_id, name, bus_id, fee_paid, parent_contact)
VALUES (?, ?, ?, ?, ?)
''', [
    ('S101', 'Aarav Mehta', 'BUS1', 1, '9876543210'),
    ('S102', 'Diya Patel', 'BUS1', 0, '9876509876')
])

conn.commit()
conn.close()
print("✅ Database setup complete — students.db created successfully!")
 