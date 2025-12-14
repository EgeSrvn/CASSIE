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
    VM_LOAD,
)
from bucket_manager import ensure_global_bucket, GLOBAL_BUCKET_NAME, upload_bytes
from db_manager import get_connection, initialize_database
from docker_commands import ensure_network, ensure_vms, assign_tenant_to_vm, create_tenant_user, get_tenant_container
import nextflow_manager

HOST = "0.0.0.0"
PORT = 5001

# Initialize database and Docker network/VMs
initialize_database()
ensure_network()
ensure_vms()
ensure_global_bucket()  # make sure the shared MinIO bucket exists


# Lock for tenant registry updates
TENANT_LOCK = threading.Lock()


def migrate_tenants_from_db():
    """
    Load existing tenants from the database into the runtime TENANT_REGISTRY.

    This function retrieves tenant information from the database and populates
    the TENANT_REGISTRY dictionary with tenant details, including the assigned
    VM and bucket name. It also updates the VM_LOAD dictionary to reflect the
    current load on each VM.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, vm_name, user_id FROM tenants;")
    rows = cur.fetchall()
    for name, vm_name, user_id in rows:
        TENANT_REGISTRY[(name, user_id)] = {
            "vm": vm_name,
            "bucket": GLOBAL_BUCKET_NAME,
        }
        if vm_name in VM_LOAD:
            VM_LOAD[vm_name] += 1
    cur.close()
    conn.close()
    print(f"[*] Migrated {len(rows)} tenants from database.")



migrate_tenants_from_db()


def handle_client(conn, addr):
    """
    Handle an individual client connection.

    This function manages the interaction with a connected client, including:
    - Authenticating the user by username.
    - Displaying a menu for tenant management operations.
    - Handling user input to perform operations such as adding, removing, or
      listing tenants, and opening a terminal for a tenant.

    Args:
        conn (socket.socket): The socket connection to the client.
        addr (tuple): The address of the connected client.
    """

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
            "6. Upload file\n"
            "7. Generate & Run Pipeline\n"
            "8. Exit\n"
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
                    TENANT_REGISTRY[key] = {"vm": assigned_vm, "bucket": GLOBAL_BUCKET_NAME}
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
                TENANT_REGISTRY[key] = {"vm": assigned_vm, "bucket": GLOBAL_BUCKET_NAME}
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
            # Ask which tenant (optional, only for UI)
            tenants = show_user_tenants(user_id)
            if not tenants:
                conn.sendall(b"No tenants found. Create a tenant first.\n")
                continue

            tenant_list = "\n".join([f"{i+1}. {t[0]}" for i, t in enumerate(tenants)]) + "\n"
            conn.sendall(b"Select tenant for this upload:\n" + tenant_list.encode())
            selection = conn.recv(1024).decode().strip()
            try:
                idx = int(selection) - 1
                tenant_name = tenants[idx][0]
            except:
                conn.sendall(b"Invalid selection.\n")
                continue

            # Receive filename
            conn.sendall(b"Enter filename (or keep original): ")
            filename = conn.recv(4096).decode().strip()
            if not filename:
                filename = "uploaded.bin"

            # Receive file size (as ASCII int)
            conn.sendall(b"Enter file size in bytes: ")
            size_str = conn.recv(1024).decode().strip()
            try:
                size = int(size_str)
            except:
                conn.sendall(b"Invalid size.\n")
                continue

            conn.sendall(b"Send file bytes now...\n")

            # Receive exactly size bytes
            buf = bytearray()
            remaining = size
            while remaining > 0:
                chunk = conn.recv(min(65536, remaining))
                if not chunk:
                    break
                buf.extend(chunk)
                remaining -= len(chunk)

            if remaining != 0:
                conn.sendall(b"Upload failed: connection dropped early.\n")
                continue

            # Upload to MinIO under username/uploads/
            try:
                _, key = upload_bytes(username=username, filename=filename, data=bytes(buf), prefix="uploads")
                msg = f"Uploaded to bucket as: {key}\nTenant '{tenant_name}' can download it.\n"
                conn.sendall(msg.encode())
            except Exception as e:
                conn.sendall(f"Upload failed: {e}\n".encode())

        elif choice == "7": # Generate & Run Pipeline
            # 1. Select Tenant
            tenants = show_user_tenants(user_id)
            if not tenants:
                conn.sendall(b"No tenants found. Create a tenant first.\n")
                continue

            tenant_list = "\n".join([f"{i+1}. {t[0]}" for i, t in enumerate(tenants)]) + "\n"
            conn.sendall(b"Select tenant to run pipeline:\n" + tenant_list.encode())
            selection = conn.recv(1024).decode().strip()
            try:
                idx = int(selection) - 1
                tenant_name = tenants[idx][0]
            except:
                conn.sendall(b"Invalid selection.\n")
                continue
            
            # 2. List Tools
            tools = nextflow_manager.get_tool_list()
            tool_menu = "\n".join([f"{i}. {name}" for i, name in enumerate(tools)])
            conn.sendall(f"Available Tools:\n{tool_menu}\nEnter tool indices (comma separated, e.g., 0,2): ".encode())
            
            indices_str = conn.recv(1024).decode().strip()
            indices = [x.strip() for x in indices_str.split(",") if x.strip().isdigit()]
            
            # 3. Input Data Path
            conn.sendall(b"Enter initial input data path (absolute path inside tenant): ")
            input_path = conn.recv(1024).decode().strip()
            
            conn.sendall(b"Submitting pipeline... (this may take a moment)\n")
            
            try:
                # Get the actual container object
                cont = get_tenant_container(tenant_name, user_id)
                
                # Run
                result = nextflow_manager.run_pipeline(cont, input_path, indices)
                conn.sendall(f"\n{result}\n".encode())
            except Exception as e:
                conn.sendall(f"Pipeline execution error: {e}\n".encode())

            
        elif choice == "8":
            conn.sendall(b"Goodbye!\n")
            break

        else:
            conn.sendall(b"Invalid option.\n")

    conn.close()


def start_server():
    """
    Start the TCP server to handle client connections.

    This function initializes a socket server that listens for incoming
    connections on the specified HOST and PORT. For each connection, it spawns
    a new thread to handle the client using the `handle_client` function.
    """
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
