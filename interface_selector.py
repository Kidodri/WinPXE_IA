import psutil
import socket

def get_interfaces():
    interfaces = []
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()

    for name, snicaddrs in addrs.items():
        # Only interested in up and non-loopback interfaces
        if name in stats and stats[name].isup:
            for addr in snicaddrs:
                if addr.family == socket.AF_INET:
                    interfaces.append({
                        "name": name,
                        "ip": addr.address,
                        "mask": addr.netmask
                    })
    return interfaces

def select_interface():
    interfaces = get_interfaces()
    if not interfaces:
        print("No active network interfaces found.")
        return None

    print("\nSelect the network interface to use for the PXE server:")
    for i, iface in enumerate(interfaces):
        print(f"[{i}] {iface['name']} - {iface['ip']} (Mask: {iface['mask']})")

    while True:
        try:
            choice = int(input(f"\nEnter choice (0-{len(interfaces)-1}): "))
            if 0 <= choice < len(interfaces):
                return interfaces[choice]
        except ValueError:
            pass
        print(f"Invalid selection. Please enter a number between 0 and {len(interfaces)-1}.")

if __name__ == "__main__":
    selected = select_interface()
    if selected:
        print(f"\nYou selected: {selected['name']} with IP {selected['ip']}")
