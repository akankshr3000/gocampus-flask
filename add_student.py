import sqlite3

conn = sqlite3.connect("database/students.db")
c = conn.cursor()

# Ask user for details
student_id = input("Enter Student ID (e.g. S104): ")
name = input("Enter Student Name: ")
bus_id = input("Enter Bus ID (e.g. BUS2): ")
fee_paid = int(input("Enter Fee Paid Status (1 = Paid, 0 = Unpaid): "))
parent_contact = input("Enter Parent Contact: ")

# Insert into database
c.execute(
    "INSERT INTO students (student_id, name, bus_id, fee_paid, parent_contact) VALUES (?, ?, ?, ?, ?)",
    (student_id, name, bus_id, fee_paid, parent_contact),
)

conn.commit()
conn.close()
print(f"✅ Student {name} added successfully!")
 