import time
from docker_commands import (
    ensure_network,
    ensure_vms,
    list_vms,
    start_vm,
    stop_vm,
    execute_in_vm,
    start_all,
    stop_all
)

def main():
    ensure_network()
    ensure_vms()
    while True:
        print("""
                ==== VM Control Panel ====
                1. List vms
                2. Start a vm
                3. Stop a vm
                4. Start all
                5. Stop all
                6. Execute command in VM
                7. Exit
                ===========================
                """)
        choice = input("Enter choice: ").strip()

        if choice == "1":
            list_vms()
        elif choice == "2":
            name = input("Container name: ").strip()
            start_vm(name)
        elif choice == "3":
            name = input("Container name: ").strip()
            stop_vm(name)
        elif choice == "4":
            start_all()
        elif choice == "5":
            stop_all()
        elif choice == "6":
            vm_name = input("Enter VM name: ")
            command = input("Enter command to execute: ")
            execute_in_vm(vm_name, command)
        elif choice == "7":
            print("Exiting control panel...")
            break
        else:
            print("Invalid choice.")
        time.sleep(1)

if __name__ == "__main__":
    main()
