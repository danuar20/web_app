from werkzeug.security import generate_password_hash
from app.db import db_webapp

username = "infra2"
password = "12345"

hashed = generate_password_hash(password)

conn = db_webapp.get_connection()
cur = conn.cursor()

cur.execute(
    "INSERT INTO users (username, password) VALUES (%s, %s)",
    (username, hashed)
)

conn.commit()
cur.close()
conn.close()

print("User berhasil dibuat dengan password hash")