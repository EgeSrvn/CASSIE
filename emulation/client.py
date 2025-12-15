import socket
import threading
import sys

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

def main():
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
                # Generate Pipeline
                print("[*] Fetching tenant list...")
                # 1. Select Tenant
                print(receive_until_prompt(sock), end="") 
                sock.sendall((input() + "\n").encode())
                
                # 2. Select Tools
                print(receive_until_prompt(sock), end="") # Tool list + "Enter indices: "
                sock.sendall((input() + "\n").encode())
                
                # 3. Input Path
                print(receive_until_prompt(sock), end="") # "Enter path: "
                sock.sendall((input() + "\n").encode())
                
                # 4. Result
                print(receive_until_prompt(sock))

            elif choice == "8":
                print(receive_until_prompt(sock))
                print("[*] Exiting client...")
                break

            else:
                # Invalid input fallback
                print(receive_until_prompt(sock))


if __name__ == "__main__":
    main()
