# control_panel.py
from tenant_commands import add_tenant, remove_tenant, show_tenants, remove_all_tenants, TENANT_REGISTRY
from docker_commands import ensure_network, ensure_vms
from bucket_manager import init_s3_client, list_buckets, delete_all_buckets

def show_menu():
    print("\n=== TENANT CONTROL PANEL ===")
    print("1. Add Tenant")
    print("2. Show Tenants")
    print("3. List Buckets")
    print("4. Remove Tenant")
    print("5. Exit")


def main():
    ensure_network()
    ensure_vms()
    s3 = init_s3_client()

    while True:
        show_menu()
        choice = input("\nSelect option: ")

        if choice == "1":
            tenant_name = input("Enter tenant name: ")
            vm_name = input("Select VM (vm1/vm2/vm3 or leave empty for auto): ") or None
            add_tenant(tenant_name, vm_name)

        elif choice == "2":
            show_tenants()

        elif choice == "3":
            list_buckets(s3)

        elif choice == "4":
            tenant_name = input("Enter tenant name to remove: ")
            remove_tenant(tenant_name)

        elif choice == "5":
            remove_all_tenants()
            delete_all_buckets(s3)
            print("Exiting...")
            break

        else:
            print("Invalid option, try again.")

if __name__ == "__main__":
    main()