import sqlite3
sid = input("Enter student_id to delete: ").strip()
conn = sqlite3.connect("database/students.db")
c = conn.cursor()
c.execute("DELETE FROM students WHERE student_id=?", (sid,))
conn.commit()
conn.close()
print("Deleted (if existed):", sid)
  