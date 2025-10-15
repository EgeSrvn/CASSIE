# server.py
import socket
import threading
import select
from tenant_commands import (
    add_tenant,
    remove_tenant,
    show_user_tenants,
    remove_all_user_tenants,
    open_tenant_terminal,
    TENANT_REGISTRY,
    VM_CAPACITY,
    VM_LOAD,
)
from db_manager import get_connection, initialize_database
from docker_commands import ensure_network, ensure_vms, assign_tenant_to_vm, create_tenant_user

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
    cur.execute("SELECT name, vm_name, user_id FROM tenants;")
    rows = cur.fetchall()
    for name, vm_name, user_id in rows:
        TENANT_REGISTRY[(name, user_id)] = {
            "vm": vm_name,
            "bucket": f"{name}-bucket"
        }
        if vm_name in VM_LOAD:
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
            "5. Open Terminal for Tenant\n"
            "6. Exit\n"
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
                # Pass user_id into add_tenant so tenant container/user is created there
                add_tenant(tenant_name, vm_name=vm_choice, user_id=user_id)

                # Ensure tenant has an assigned VM in runtime registry or assign now
                key = (tenant_name, user_id)
                if key in TENANT_REGISTRY:
                    assigned_vm = TENANT_REGISTRY[key]["vm"]
                else:
                    # Not present in runtime (defensive): assign and update registry minimally
                    assigned_vm = assign_tenant_to_vm(tenant_name, user_id)
                    TENANT_REGISTRY[key] = {"vm": assigned_vm, "bucket": f"user-{user_id}-bucket"}
                    VM_LOAD[assigned_vm] += 1

            conn.sendall(f"Tenant '{tenant_name}' added and assigned to {assigned_vm}.\n".encode())
        
        elif choice == "2":
            conn.sendall(b"Enter tenant name to remove: ")
            tenant_name = conn.recv(1024).decode().strip()
            with TENANT_LOCK:
                # pass user_id so correct tenant instance is removed
                remove_tenant(tenant_name, user_id)
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
            tenants = show_user_tenants(user_id)
            if not tenants:
                conn.sendall(b"No tenants found.\n")
                continue

            tenant_list = "\n".join([f"{i+1}. {t[0]}" for i, t in enumerate(tenants)]) + "\n"
            conn.sendall(b"Select tenant:\n" + tenant_list.encode())
            selection = conn.recv(1024).decode().strip()
            try:
                idx = int(selection)-1
                tenant_name = tenants[idx][0]
            except:
                conn.sendall(b"Invalid selection.\n")
                continue


            key = (tenant_name, user_id)
            if key in TENANT_REGISTRY:
                assigned_vm = TENANT_REGISTRY[key]["vm"]
            else:
                # fallback: assign tenant to a VM and create tenant user (include user_id)
                assigned_vm = assign_tenant_to_vm(tenant_name, user_id)
                TENANT_REGISTRY[key] = {"vm": assigned_vm, "bucket": f"user-{user_id}-bucket"}
                VM_LOAD[assigned_vm] += 1
                try:
                    create_tenant_user(assigned_vm, tenant_name, user_id)
                except Exception as e:
                    print(f"[!] Warning: failed to create tenant user in {assigned_vm}: {e}")

            result = open_tenant_terminal(tenant_name, user_id)
            if isinstance(result, str):
                conn.sendall(result.encode() + b"\n")
                continue

            docker_sock = result
            real_sock = getattr(docker_sock, "sock", getattr(docker_sock, "_sock", docker_sock))

            conn.sendall(b"--- Interactive tenant shell opened. Type /exit on a line to quit. ---\n")

            # Try select-based relay first
            if hasattr(real_sock, "fileno"):
                try:
                    conn.setblocking(False)
                    real_sock.setblocking(False)
                except Exception:
                    pass

                try:
                    while True:
                        rlist, _, _ = select.select([conn, real_sock], [], [], 0.1)
                        if conn in rlist:
                            try:
                                data = conn.recv(4096)
                            except BlockingIOError:
                                data = b""
                            if data == b"":
                                continue
                            if data.strip() == b"/exit":
                                break
                            try:
                                real_sock.sendall(data)
                            except Exception:
                                break

                        if real_sock in rlist:
                            try:
                                data = real_sock.recv(4096)
                            except BlockingIOError:
                                data = b""
                            if not data:
                                break
                            try:
                                conn.sendall(data)
                            except Exception:
                                break
                except Exception as e:
                    print(f"[!] Interactive relay error: {e}")
                finally:
                    try:
                        docker_sock.close()
                    except Exception:
                        try:
                            real_sock.close()
                        except Exception:
                            pass
                    try:
                        conn.sendall(b"\n--- Tenant shell closed. ---\n")
                    except Exception:
                        pass
                    try:
                        conn.setblocking(True)
                    except Exception:
                        pass
            else:
                # Fallback: relay with a thread if select() can't be used
                def relay_output():
                    try:
                        while True:
                            data = docker_sock.recv(4096)
                            if not data:
                                break
                            conn.sendall(data)
                    except Exception:
                        pass

                t = threading.Thread(target=relay_output, daemon=True)
                t.start()

                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    if data.strip() == b"/exit":
                        break
                    docker_sock.send(data)

                docker_sock.close()
                conn.sendall(b"\n--- Tenant shell closed. ---\n")



            
        elif choice == "6":
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
