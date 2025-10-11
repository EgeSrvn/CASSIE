import socket

HOST = "127.0.0.1"  # Server address
PORT = 5000         # Server port

def receive_until_prompt(sock):
    """Receive data until the server sends a menu/prompt (ends with ': ' or '\n')."""
    data = b""
    while True:
        chunk = sock.recv(1024)
        if not chunk:
            break
        data += chunk
        # Basic heuristic: server prompt ends with ': ' or full message
        if b": " in chunk or b"\n" in chunk:
            break
    return data.decode()

def main():
    print(f"[*] Connecting to server {HOST}:{PORT}...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))
        print("[+] Connected to server.")

        # Initial login
        prompt = receive_until_prompt(sock)
        username = input(prompt)
        sock.sendall(username.encode())

        # Receive login confirmation
        confirmation = receive_until_prompt(sock)
        print(confirmation)

        # Main client loop
        while True:
            menu = receive_until_prompt(sock)
            choice = input(menu)
            sock.sendall(choice.encode())

            # Handle special prompts from server (tenant names, VM selection, etc.)
            if choice in ["1", "2"]:
                # Server asks for tenant name
                prompt = receive_until_prompt(sock)
                tenant_name = input(prompt)
                sock.sendall(tenant_name.encode())

                if choice == "1":  # Adding tenant may ask for VM
                    prompt = receive_until_prompt(sock)
                    vm_name = input(prompt)
                    sock.sendall(vm_name.encode())

            # Receive server response
            response = receive_until_prompt(sock)
            print(response)

            if choice == "5":
                print("[*] Exiting client...")
                break

if __name__ == "__main__":
    main()
