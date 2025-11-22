import sqlite3

conn = sqlite3.connect("database/students.db")
c = conn.cursor()

# Add some sample students
students = [
    ("S101", "Aarav Mehta", "BUS1", 1, "9876543210"),
    ("S102", "Diya Patel", "BUS1", 0, "9876509876"),
    ("S103", "Rohan Singh", "BUS2", 0, "9876512345")
]

c.executemany("INSERT OR IGNORE INTO students (student_id, name, bus_id, fee_paid, parent_contact) VALUES (?, ?, ?, ?, ?)", students)
conn.commit()
conn.close()

print("✅ Sample students inserted successfully!")
 