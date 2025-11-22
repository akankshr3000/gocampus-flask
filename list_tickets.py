import sqlite3
import os

DB_PATH = os.path.join(os.getcwd(), "database", "students.db")
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("SELECT id, name, issue FROM help_tickets")
rows = c.fetchall()
conn.close()

with open("tickets.txt", "w") as f:
    for row in rows:
        f.write(f"{row}\n")
