import sqlite3
conn = sqlite3.connect("database.db")
conn.execute("ALTER TABLE cars ADD COLUMN year INTEGER;")
conn.execute("ALTER TABLE cars ADD COLUMN mileage INTEGER;")
conn.commit()
conn.close()