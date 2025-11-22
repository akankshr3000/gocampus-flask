import sqlite3
import os
from datetime import datetime

# Database path
db_path = os.path.join(os.getcwd(), "database", "students.db")

def migrate_database():
    """Migrate database to add new fields and tables for GoCampus Extension"""
    if not os.path.exists(db_path):
        print("Database does not exist. Run database_setup.py first.")
        return
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    try:
        # Check if new columns exist in students table
        c.execute("PRAGMA table_info(students)")
        columns = [col[1] for col in c.fetchall()]
        
        # List of new columns to add
        new_columns = {
            'semester': 'TEXT DEFAULT NULL',
            'branch': 'TEXT DEFAULT NULL',
            'amount_paid': 'INTEGER DEFAULT NULL',
            'transaction_date': 'TEXT DEFAULT NULL',
            'email': 'TEXT DEFAULT NULL',
            'photo_filename': 'TEXT DEFAULT NULL',
            'registration_date': 'TEXT DEFAULT NULL',
            'valid_till': 'TEXT DEFAULT NULL',
            'current_sem': 'INTEGER DEFAULT NULL',
            'is_active_transport': 'INTEGER DEFAULT 0'
        }

        for col_name, col_def in new_columns.items():
            if col_name not in columns:
                c.execute(f"ALTER TABLE students ADD COLUMN {col_name} {col_def}")
                print(f"Added '{col_name}' column")
        
        # Create HelpTickets table
        c.execute("""
            CREATE TABLE IF NOT EXISTS help_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                usn TEXT NOT NULL,
                email TEXT NOT NULL,
                issue TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'Open'
            )
        """)
        print("Ensured 'help_tickets' table exists")

        # Create RenewalHistory table
        c.execute("""
            CREATE TABLE IF NOT EXISTS renewal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                renewed_date TEXT NOT NULL,
                previous_valid_till TEXT,
                new_valid_till TEXT,
                FOREIGN KEY(student_id) REFERENCES students(student_id)
            )
        """)
        print("Ensured 'renewal_history' table exists")
        
        conn.commit()
        print("Database migration completed successfully!")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()

