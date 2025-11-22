import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.getcwd(), "database", "students.db")

def get_columns():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA table_info(help_tickets)")
    cols = [row[1] for row in c.fetchall()]
    conn.close()
    return cols

def verify_schema():
    cols = get_columns()
    if "resolved_at" in cols:
        print("PASS: resolved_at column exists.")
    else:
        print("FAIL: resolved_at column MISSING.")

def test_cleanup():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Insert old resolved ticket
    old_date = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO help_tickets (name, usn, email, issue, timestamp, status, resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
              ("Old Ticket", "USN1", "test@test.com", "Old Issue", old_date, "Resolved", old_date))
    old_id = c.lastrowid
    
    # Insert recent resolved ticket
    new_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO help_tickets (name, usn, email, issue, timestamp, status, resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
              ("New Ticket", "USN2", "test@test.com", "New Issue", new_date, "Resolved", new_date))
    new_id = c.lastrowid
    
    conn.commit()
    print(f"Inserted Old Ticket ID: {old_id}, New Ticket ID: {new_id}")
    
    # Run cleanup logic (copy-pasted from app.py for verification of the SQL)
    print("Running cleanup logic...")
    c.execute("DELETE FROM help_tickets WHERE status='Resolved' AND resolved_at <= datetime('now', '-5 days')")
    conn.commit()
    
    # Verify
    c.execute("SELECT id FROM help_tickets WHERE id=?", (old_id,))
    if c.fetchone() is None:
        print("PASS: Old ticket deleted.")
    else:
        print("FAIL: Old ticket still exists.")
        
    c.execute("SELECT id FROM help_tickets WHERE id=?", (new_id,))
    if c.fetchone():
        print("PASS: New ticket preserved.")
    else:
        print("FAIL: New ticket deleted.")

    # Cleanup test data
    c.execute("DELETE FROM help_tickets WHERE id IN (?, ?)", (old_id, new_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    # Simulate migration if needed (since app restart isn't guaranteed here)
    cols = get_columns()
    if "resolved_at" not in cols:
        print("Simulating migration for test...")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("ALTER TABLE help_tickets ADD COLUMN resolved_at TEXT")
            conn.commit()
        except Exception as e:
            print(f"Migration failed: {e}")
        conn.close()
        
    verify_schema()
    test_cleanup()
