import socket
import threading
import sys

HOST = "127.0.0.1"  # Server address
PORT = 5001        # Server port


def receive_until_prompt(sock):
    """
    Receive data from the server until a prompt or full message is received.

    This function reads data from the socket in chunks until it detects
    the end of a message, which is determined by the data ending with
    ': ' or '\n'. The received data is then decoded and returned.

    Args:
        sock (socket.socket): The socket object to receive data from.

    Returns:
        str: The decoded data received from the server.
    """
    data = b""
    while True:
        chunk = sock.recv(1024)
        if not chunk:
            break
        data += chunk
        # Heuristic: stop when prompt or full message is received
        if data.endswith(b": ") or data.endswith(b"\n"):
            break
    return data.decode(errors="replace")


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

                # Start a reader thread to print server -> client output
                stop_event = threading.Event()

                def reader():
                    """
                    Thread function to continuously read and print data from the server.

                    This function runs in a separate thread and reads data from the
                    server socket, printing it to the standard output. It stops when
                    the `stop_event` is set or the server closes the connection.
                    """
                    try:
                        while not stop_event.is_set():
                            data = sock.recv(4096)
                            if not data:
                                break
                            # decode and print raw bytes
                            sys.stdout.write(data.decode(errors="replace"))
                            sys.stdout.flush()
                    except Exception:
                        pass

                t = threading.Thread(target=reader, daemon=True)
                t.start()

                print("[*] Enter interactive tenant shell. Type /exit on a line to quit.")
                try:
                    while True:
                        try:
                            line = input()
                        except EOFError:
                            break
                        if line.strip() == "/exit":
                            sock.sendall(("/exit\n").encode())
                            break
                        sock.sendall((line + "\n").encode())
                except KeyboardInterrupt:
                    try:
                        sock.sendall(("/exit\n").encode())
                    except Exception:
                        pass

                stop_event.set()
                # allow reader thread to drain
                t.join(timeout=1)
                # print any remaining data
                try:
                    print(receive_until_prompt(sock), end="")
                except Exception:
                    pass

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
                print(receive_until_prompt(sock))
                print("[*] Exiting client...")
                break

            else:
                # Invalid input fallback
                print(receive_until_prompt(sock))


if __name__ == "__main__":
    main()
