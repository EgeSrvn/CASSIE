import socket
import threading
import os
import sys

"""
Cloud Emulator Client
=====================

This client connects to the Cloud Emulator Server (default 127.0.0.1:5001).
It supports two modes: Interactive (Menu-based) and Command Line Interface (CLI).

USAGE
-----
1. Interactive Mode:
   Run without arguments to enter the interactive menu.
   $ python3 client.py

2. CLI Mode:
   Run with the `-cli` flag to execute a single command and exit immediately 
   (except for 'open_terminal' which stays open).
   
   General Syntax:
   $ python3 client.py -cli <COMMAND> <USERNAME> [ARGS...]

AVAILABLE CLI COMMANDS
----------------------

1. add_tenant
   - Description: Creates a new tenant and assigns it to a VM (Docker container).
   - Usage: python3 client.py -cli add_tenant <user> <tenant_name> [vm_name]
   - Example: python3 client.py -cli add_tenant ege my_tenant vm1

2. remove_tenant
   - Description: Deletes a specific tenant and its associated container.
   - Usage: python3 client.py -cli remove_tenant <user> <tenant_name>
   - Example: python3 client.py -cli remove_tenant ege my_tenant

3. show_tenants
   - Description: Lists all tenants currently registered to the user.
   - Usage: python3 client.py -cli show_tenants <user>
   - Example: python3 client.py -cli show_tenants ege

4. remove_all
   - Description: Wipes all tenants belonging to the user.
   - Usage: python3 client.py -cli remove_all <user>
   - Example: python3 client.py -cli remove_all ege

5. open_terminal
   - Description: Connects to a running tenant's shell. 
     (Note: This command keeps the connection open until you type /exit).
   - Usage: python3 client.py -cli open_terminal <user> <tenant_name>
   - Example: python3 client.py -cli open_terminal ege my_tenant

6. upload
   - Description: Uploads a local file to the server's global bucket for a specific tenant.
   - Usage: python3 client.py -cli upload <user> <tenant_name> <local_file_path>
   - Example: python3 client.py -cli upload ege my_tenant ./data.txt

7. pipeline
   - Description: Submits a Nextflow pipeline job on a tenant's container.
   - Usage: python3 client.py -cli pipeline <user> <tenant_name> <tool_indices> "<args>"
   - Note: 'tool_indices' is a comma-separated string (e.g., "0,1") selecting tools from the server list.
   - Example: python3 client.py -cli pipeline ege my_tenant 0,1 "-fasta input.fa"
"""

HOST = "127.0.0.1"  # Server address
PORT = 5001        # Server port

END_MARKER = "<WAIT>"

BUFFER = b""

def receive_until_prompt(sock):
    """
    Reads data until the first END_MARKER is found.
    Handles cases where multiple messages arrive in one packet.
    """
    global BUFFER
    
    while True:
        # 1. Check if the marker is already in our buffer
        if END_MARKER.encode() in BUFFER:
            # Split at the FIRST marker found
            message, _, rest = BUFFER.partition(END_MARKER.encode())
            # Save the rest for the next call
            BUFFER = rest
            return message.decode(errors="replace")
        
        # 2. If not found, read more data from network
        try:
            chunk = sock.recv(4096)
            if not chunk:
                # Connection closed. Return remaining buffer if any.
                if BUFFER:
                    ret = BUFFER
                    BUFFER = b""
                    return ret.decode(errors="replace")
                break
            BUFFER += chunk
        except socket.error:
            break
            
    return ""

def send_line(sock, text):
    """Helper to send text with a newline."""
    sock.sendall((text + "\n").encode())

def interactive():
    """
    Main function to handle the client-side logic for interacting with the server.

    This function establishes a connection to the server, handles the login phase,
    and provides a menu-driven interface for the user to interact with the server.
    The user can perform various actions such as adding/removing tenants, viewing
    tenants, and entering an interactive tenant terminal.

    The function runs until the user chooses to exit the client.
    """
    print(f"[*] Connecting to server {HOST}:{PORT}...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))
        print("[+] Connected to server.")

        # Login phase
        prompt = receive_until_prompt(sock)
        username = input(prompt)
        # send newline-terminated inputs so server.recv().strip() behaves consistently
        sock.sendall((username + "\n").encode())

        confirmation = receive_until_prompt(sock)
        print(confirmation)

        # Main client loop
        while True:
            menu = receive_until_prompt(sock)
            choice = input(menu)
            sock.sendall((choice + "\n").encode())

            # --- 1. Add Tenant ---
            if choice == "1":
                prompt = receive_until_prompt(sock)
                tenant_name = input(prompt)
                sock.sendall((tenant_name + "\n").encode())

                prompt = receive_until_prompt(sock)
                vm_name = input(prompt)
                sock.sendall((vm_name + "\n").encode())

                print(receive_until_prompt(sock))

            # --- 2. Remove Tenant ---
            elif choice == "2":
                prompt = receive_until_prompt(sock)
                tenant_name = input(prompt)
                sock.sendall((tenant_name + "\n").encode())

                print(receive_until_prompt(sock))

            # --- 3. Show My Tenants ---
            elif choice == "3":
                print(receive_until_prompt(sock))

            # --- 4. Remove All Tenants ---
            elif choice == "4":
                print(receive_until_prompt(sock))

            # --- 5. Interactive Tenant Terminal ---
            elif choice == "5":
                print("[*] Fetching your tenant list...")
                tenant_list = receive_until_prompt(sock)
                print(tenant_list)

                tenant_choice = input("Select tenant (number): ")
                sock.sendall((tenant_choice + "\n").encode())

                stop_event = threading.Event()

                def reader():
                    """Background thread that listens for server output."""
                    global BUFFER
                    try:
                        while not stop_event.is_set():
                            try:
                                sock.settimeout(0.5)
                                data = sock.recv(4096)
                            except socket.timeout:
                                continue
                            except:
                                break
                            
                            if not data: break

                            text = data.decode(errors="replace")
                            
                            # --- CRITICAL FIX: Detect when shell closes ---
                            if "--- Tenant shell closed. ---" in text:
                                # 1. Split the output: Shell stuff vs Menu stuff
                                shell_part, _, menu_part = text.partition("--- Tenant shell closed. ---")
                                
                                # 2. Print the final shell message
                                sys.stdout.write(shell_part + "\n--- Tenant shell closed. ---\n")
                                sys.stdout.flush()
                                
                                # 3. Save the "Phantom Menu" into the buffer for the MAIN loop to find later
                                if menu_part:
                                    BUFFER += menu_part.encode()
                                
                                # 4. Tell the main loop to STOP waiting for input
                                stop_event.set()
                                break
                            
                            # Standard cleanup
                            if "<WAIT>" in text:
                                text = text.replace("<WAIT>", "")
                            
                            sys.stdout.write(text)
                            sys.stdout.flush()
                    except Exception:
                        pass
                    stop_event.set()

                t = threading.Thread(target=reader, daemon=True)
                t.start()

                print("[*] Enter interactive tenant shell. Type /exit on a line to quit.")
                
                # --- Main Loop Logic ---
                try:
                    while not stop_event.is_set():
                        # Check before blocking on input
                        if stop_event.is_set(): break
                        
                        # Use a select-like approach or just input(). 
                        # Since input() blocks, we rely on the user hitting Enter one last time 
                        # OR the thread setting the event.
                        
                        # We use a simple trick: if the reader sees the close signal, 
                        # it sets stop_event. The loop condition handles the rest.
                        try:
                            line = input()
                        except EOFError:
                            break
                            
                        # Double check after input returns
                        if stop_event.is_set(): break

                        if line.strip() == "/exit":
                            sock.sendall(("/exit\n").encode())
                            break
                        
                        sock.sendall((line + "\n").encode())
                        
                except (BrokenPipeError, OSError):
                    # If server cuts connection, stop gracefully
                    stop_event.set()

                # Cleanup
                stop_event.set()
                t.join(timeout=1)
                sock.setblocking(True)

            # --- 6. Exit ---
            elif choice == "6":
                # server will send tenant list prompt
                print(receive_until_prompt(sock))  # "Select tenant..."
                tenant_choice = input().strip()
                sock.sendall((tenant_choice + "\n").encode())

                # filename prompt
                prompt = receive_until_prompt(sock)
                local_path = input("Local file path to upload: ").strip()

                import os
                if not os.path.isfile(local_path):
                    print("File not found.")
                    # still need to respond something reasonable; send dummy and bail
                    sock.sendall(("uploaded.bin\n").encode())
                    print(receive_until_prompt(sock))
                    sock.sendall(("0\n").encode())
                    print(receive_until_prompt(sock))
                    continue

                filename = os.path.basename(local_path)
                sock.sendall((filename + "\n").encode())

                # size prompt
                print(receive_until_prompt(sock))
                size = os.path.getsize(local_path)
                sock.sendall((str(size) + "\n").encode())

                # "Send file bytes now..."
                print(receive_until_prompt(sock))

                # send bytes
                with open(local_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        sock.sendall(chunk)

                # server response
                print(receive_until_prompt(sock))
            
            elif choice == "7":
                print("[*] Fetching tenant list...")
                # 1. Select Tenant
                print(receive_until_prompt(sock), end="") 
                sock.sendall((input() + "\n").encode())
                
                # 2. Select Tools
                print(receive_until_prompt(sock), end="") # Tool list
                sock.sendall((input() + "\n").encode())
                
                # 3. Input Arguments (UPDATED)
                # Server will send: "Enter input parameters (e.g. -fasta f.fa -fastq fwd.fq -fastq rev.fq): "
                print(receive_until_prompt(sock), end="") 
                args_input = input()
                sock.sendall((args_input + "\n").encode())
                
                # 4. Result
                print(receive_until_prompt(sock))

            elif choice == "8":
                print(receive_until_prompt(sock))
                print("[*] Exiting client...")
                break

            else:
                # Invalid input fallback
                print(receive_until_prompt(sock))

def get_tenant_index(list_text, tenant_name):
    """Parses the server's list response to find the index of a tenant."""
    # Expected format: "1. name\n2. other"
    for line in list_text.splitlines():
        parts = line.strip().split(". ")
        if len(parts) >= 2:
            idx_str = parts[0]
            name = parts[1]
            if name == tenant_name:
                return idx_str
    return None
def start_terminal_loop(sock):
    """
    Handles the read/write loop for the interactive terminal.
    Used by both interactive() and cli() modes.
    """
    stop_event = threading.Event()

    def reader():
        """Background thread that listens for server output."""
        global BUFFER
        try:
            while not stop_event.is_set():
                try:
                    sock.settimeout(0.5)
                    data = sock.recv(4096)
                except socket.timeout:
                    continue
                except:
                    break
                
                if not data: break

                text = data.decode(errors="replace")
                
                # --- Detect when shell closes ---
                if "--- Tenant shell closed. ---" in text:
                    shell_part, _, menu_part = text.partition("--- Tenant shell closed. ---")
                    
                    sys.stdout.write(shell_part + "\n--- Tenant shell closed. ---\n")
                    sys.stdout.flush()
                    
                    if menu_part:
                        BUFFER += menu_part.encode()
                    
                    stop_event.set()
                    break
                
                if "<WAIT>" in text:
                    text = text.replace("<WAIT>", "")
                
                sys.stdout.write(text)
                sys.stdout.flush()
        except Exception:
            pass
        stop_event.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    print("[*] Enter interactive tenant shell. Type /exit on a line to quit.")
    
    # --- Main Input Loop ---
    try:
        while not stop_event.is_set():
            if stop_event.is_set(): break
            
            try:
                line = input()
            except EOFError:
                break
                
            if stop_event.is_set(): break

            if line.strip() == "/exit":
                send_line(sock, "/exit")
                break
            
            send_line(sock, line)
            
    except (BrokenPipeError, OSError):
        stop_event.set()

    stop_event.set()
    t.join(timeout=1)
    sock.setblocking(True)

def cli():
    """
    Handles command-line interface execution.
    Usage: python client.py -cli <command> <username> [args...]
    """
    args = sys.argv
    # args[0]=client.py, args[1]=-cli
    if len(args) < 4:
        print("Usage: python client.py -cli <command> <username> [args...]")
        print("Commands: add_tenant, show_tenants, open_terminal, upload, ...")
        return

    command = args[2]
    username = args[3]

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.connect((HOST, PORT))
        except ConnectionRefusedError:
            print("[!] Could not connect to server.")
            return

        # 1. Login Handshake
        receive_until_prompt(sock)  # Welcome prompt
        send_line(sock, username)
        receive_until_prompt(sock)  # Logged in confirmation
        
        # 2. Wait for Main Menu
        receive_until_prompt(sock)

        # 3. Execute Command
        if command == "add_tenant":
            # Usage: ... add_tenant <user> <tenant_name> [vm_name]
            if len(args) < 5:
                print("Usage: ... add_tenant <user> <tenant_name> [vm_name]")
                return
            t_name = args[4]
            vm_name = args[5] if len(args) > 5 else ""

            send_line(sock, "1")
            receive_until_prompt(sock) # "Enter tenant name"
            send_line(sock, t_name)
            receive_until_prompt(sock) # "Enter VM"
            send_line(sock, vm_name)
            print(receive_until_prompt(sock)) # Success message

        elif command == "remove_tenant":
            # Usage: ... remove_tenant <user> <tenant_name>
            if len(args) < 5:
                print("Usage: ... remove_tenant <user> <tenant_name>")
                return
            t_name = args[4]
            
            send_line(sock, "2")
            receive_until_prompt(sock) # "Enter tenant name to remove"
            send_line(sock, t_name)
            print(receive_until_prompt(sock))

        elif command == "show_tenants":
            send_line(sock, "3")
            print(receive_until_prompt(sock))

        elif command == "remove_all":
            send_line(sock, "4")
            print(receive_until_prompt(sock))

        elif command == "open_terminal":
            # Usage: ... open_terminal <user> <tenant_name>
            if len(args) < 5:
                print("Usage: ... open_terminal <user> <tenant_name>")
                return
            t_name = args[4]

            send_line(sock, "5") # Select Open Terminal
            list_text = receive_until_prompt(sock) # Get list
            
            idx = get_tenant_index(list_text, t_name)
            if not idx:
                print(f"Error: Tenant '{t_name}' not found.")
                return
            
            send_line(sock, idx)
            # Enter the terminal loop (same as interactive)
            start_terminal_loop(sock)

        elif command == "upload":
            # Usage: ... upload <user> <tenant_name> <path>
            if len(args) < 6:
                print("Usage: ... upload <user> <tenant_name> <path>")
                return
            t_name = args[4]
            local_path = args[5]

            if not os.path.isfile(local_path):
                print(f"Error: File '{local_path}' not found.")
                return

            send_line(sock, "6") # Select Upload
            list_text = receive_until_prompt(sock)
            
            idx = get_tenant_index(list_text, t_name)
            if not idx:
                print(f"Error: Tenant '{t_name}' not found.")
                return

            send_line(sock, idx)

            receive_until_prompt(sock) # Enter filename
            filename = os.path.basename(local_path)
            send_line(sock, filename)

            receive_until_prompt(sock) # Enter size
            size = os.path.getsize(local_path)
            send_line(sock, str(size))

            receive_until_prompt(sock) # Send bytes
            with open(local_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk: break
                    sock.sendall(chunk)
            
            print(receive_until_prompt(sock)) # Success message

        elif command == "pipeline":
             # Usage: ... pipeline <user> <tenant> <tools_idx> <pipeline_args>
             if len(args) < 7:
                 print("Usage: ... pipeline <user> <tenant> <tools_idx> <pipeline_args>")
                 return
             
             t_name = args[4]
             tools = args[5]
             p_args = args[6]

             send_line(sock, "7")
             list_text = receive_until_prompt(sock)
             
             idx = get_tenant_index(list_text, t_name)
             if not idx:
                 print(f"Error: Tenant '{t_name}' not found.")
                 return
            
             send_line(sock, idx)
             receive_until_prompt(sock) # Tool list
             send_line(sock, tools)
             receive_until_prompt(sock) # input params
             send_line(sock, p_args)
             print(receive_until_prompt(sock))

        else:
            print(f"Unknown command: {command}")
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "-cli":
        cli()
    else:
        interactive()
