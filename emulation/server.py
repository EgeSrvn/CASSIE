# server.py
import socket
import threading
from tenant_commands import (
    add_tenant,
    remove_tenant,
    show_user_tenants,
    remove_all_user_tenants,
    TENANT_REGISTRY,
    VM_CAPACITY,
    VM_LOAD,
)
from db_manager import get_connection, initialize_database
from docker_commands import ensure_network, ensure_vms

HOST = "0.0.0.0"
PORT = 5000

# Initialize database and Docker network/VMs
initialize_database()
ensure_network()
ensure_vms()

# Lock for tenant registry updates
TENANT_LOCK = threading.Lock()


def migrate_tenants_from_db():
    """Load existing tenants from DB into runtime TENANT_REGISTRY."""
    conn = get_connection()
    cur = conn.cursor()
    # Fetch tenant name, vm_name, and user_id
    cur.execute("SELECT name, vm_name, user_id FROM tenants;")
    rows = cur.fetchall()
    for name, vm_name, user_id in rows:
        TENANT_REGISTRY[(name, user_id)] = {
            "vm": vm_name,
            "bucket": f"{name}-bucket"
        }
        VM_LOAD[vm_name] += 1
    cur.close()
    conn.close()
    print(f"[*] Migrated {len(rows)} tenants from database.")



migrate_tenants_from_db()


def handle_client(conn, addr):
    """Handle individual client connection."""
    conn.sendall(b"Welcome to Cloud Emulator!\nEnter username: ")
    username = conn.recv(1024).decode().strip()
    if not username:
        conn.sendall(b"Invalid username. Closing connection.\n")
        conn.close()
        return

    # Get or create user_id in DB
    conn_db = get_connection()
    cur = conn_db.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s;", (username,))
    row = cur.fetchone()
    if row:
        user_id = row[0]
    else:
        cur.execute(
            "INSERT INTO users (username) VALUES (%s) RETURNING id;", (username,)
        )
        user_id = cur.fetchone()[0]
        conn_db.commit()
    cur.close()
    conn_db.close()

    conn.sendall(f"Logged in as {username} (user_id={user_id})\n".encode())

    while True:
        menu = (
            "\n=== CLIENT MENU ===\n"
            "1. Add Tenant\n"
            "2. Remove Tenant\n"
            "3. Show My Tenants\n"
            "4. Remove All My Tenants\n"
            "5. Exit\n"
            "Select option: "
        )
        conn.sendall(menu.encode())
        choice = conn.recv(1024).decode().strip()

        if choice == "1":
            # Ask VM choice or auto-assign
            conn.sendall(b"Enter tenant name: ")
            tenant_name = conn.recv(1024).decode().strip()
            conn.sendall(b"Select VM (vm1/vm2/vm3) or leave empty for auto: ")
            vm_choice = conn.recv(1024).decode().strip() or None

            with TENANT_LOCK:
                add_tenant(tenant_name, vm_name=vm_choice, user_id=user_id)
            conn.sendall(f"Tenant '{tenant_name}' added.\n".encode())

        elif choice == "2":
            conn.sendall(b"Enter tenant name to remove: ")
            tenant_name = conn.recv(1024).decode().strip()
            with TENANT_LOCK:
                remove_tenant(tenant_name)
            conn.sendall(f"Tenant '{tenant_name}' removed.\n".encode())

        elif choice == "3":
            tenants = show_user_tenants(user_id)
            if not tenants:
                conn.sendall(b"No tenants found.\n")
            else:
                tenant_list = "\n".join([f"{t[0]} → {t[1]}" for t in tenants]) + "\n"
                conn.sendall(tenant_list.encode())

        elif choice == "4":
            with TENANT_LOCK:
                remove_all_user_tenants(user_id)
            conn.sendall(b"All your tenants removed.\n")

        elif choice == "5":
            conn.sendall(b"Goodbye!\n")
            break

        else:
            conn.sendall(b"Invalid option.\n")

    conn.close()


def start_server():
    """Start the TCP server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        print(f"[*] Server listening on {HOST}:{PORT}...")
        while True:
            conn, addr = s.accept()
            print(f"[*] Connection from {addr}")
            client_thread = threading.Thread(target=handle_client, args=(conn, addr))
            client_thread.daemon = True
            client_thread.start()


if __name__ == "__main__":
    start_server()
