"""
seed_demo_users.py — Garante que os usuários admin e de demonstração estejam cadastrados e com senhas válidas no users.db.
"""
import sqlite3
import os
from pathlib import Path
from src.sql_agent.auth.security import hash_password

DB_PATH = Path("data/users.db").resolve()
os.makedirs(DB_PATH.parent, exist_ok=True)

conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

# 1. Admin
c.execute("SELECT id FROM users WHERE LOWER(username) = 'admin';")
row = c.fetchone()
admin_hash = hash_password("123")
if not row:
    c.execute("""
        INSERT INTO users (name, username, email, password_hash, tag, bu, tags, is_active, approval_status, created_at)
        VALUES ('Administrador', 'admin', 'admin@empresa.com', ?, 'ADM', 'Corporativo', 'ADM,Fiscal,Contabil', 1, 'approved', datetime('now'));
    """, (admin_hash,))
    print("Created admin user")
else:
    c.execute("""
        UPDATE users SET password_hash = ?, is_active = 1, approval_status = 'approved', bu = 'Corporativo', tags = 'ADM,Fiscal,Contabil'
        WHERE id = ?;
    """, (admin_hash, row[0]))
    print("Updated admin user")

# 2. Demo users
demo_users = [
    ("Demo Analyst", "demo.analyst", "demo.analyst@empresa.com", "demo123", "Varejo", "Varejo", "Varejo", 1, "approved"),
    ("Demo Fiscal", "demo.fiscal", "demo.fiscal@empresa.com", "demo123", "Fiscal", "Fiscal", "Fiscal", 1, "approved"),
    ("Demo Contabil", "demo.contabil", "demo.contabil@empresa.com", "demo123", "Contabil", "Contabil", "Contabil", 1, "approved"),
    ("Demo Viewer", "demo.viewer", "demo.viewer@empresa.com", "demo123", "Varejo", "Varejo", "Varejo", 0, "pending"),
    # Usuários legados para compatibilidade retroativa
    ("Controladoria", "controladoria", "controladoria@empresa.com", "123", "ADM", "Corporativo", "ADM,Fiscal,Contabil", 1, "approved"),
    ("Carlos Varejo", "carlos.varejo", "carlos.varejo@empresa.com", "123456", "Varejo", "Varejo", "Varejo", 1, "approved"),
]

for name, uname, email, pwd, tag, bu, tags, active, status in demo_users:
    c.execute("SELECT id FROM users WHERE LOWER(username) = ?;", (uname.lower(),))
    existing = c.fetchone()
    pwd_h = hash_password(pwd)
    if not existing:
        # Check if email is already taken
        c.execute("SELECT id FROM users WHERE LOWER(email) = ?;", (email.lower(),))
        email_match = c.fetchone()
        if email_match:
            c.execute("""
                UPDATE users SET name = ?, username = ?, password_hash = ?, tag = ?, bu = ?, tags = ?, is_active = ?, approval_status = ?
                WHERE id = ?;
            """, (name, uname.lower(), pwd_h, tag, bu, tags, active, status, email_match[0]))
            print(f"Updated user by email {uname}")
        else:
            c.execute("""
                INSERT INTO users (name, username, email, password_hash, tag, bu, tags, is_active, approval_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'));
            """, (name, uname.lower(), email.lower(), pwd_h, tag, bu, tags, active, status))
            print(f"Created user {uname}")
    else:
        c.execute("""
            UPDATE users SET password_hash = ?, is_active = ?, approval_status = ?, bu = ?, tags = ?, name = ?
            WHERE id = ?;
        """, (pwd_h, active, status, bu, tags, name, existing[0]))
        print(f"Updated user {uname}")

conn.commit()
conn.close()
print("All users seeded/updated successfully in data/users.db")
