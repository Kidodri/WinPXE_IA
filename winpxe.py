import os
import sys
import time
from interface_selector import select_interface
from proxydhcp import ProxyDHCP
from tftp_server import TFTPServer
from http_server import HTTPServer, generate_ipxe_menu

def main():
    print("=== WinPXE Python Server ===")

    # 1. Check for bootloaders
    import setup_bootloaders
    setup_bootloaders.ensure_bootloaders()

    # 2. Select Interface
    iface = select_interface()
    if not iface:
        sys.exit(1)

    server_ip = iface['ip']
    interface_name = iface['name']

    # 3. Generate iPXE Menu
    iso_dir = "isos"
    if not os.path.exists(iso_dir):
        os.makedirs(iso_dir)

    generate_ipxe_menu(iso_dir, server_ip, 80)

    # 4. Start Servers
    # We'll use a slightly modified boot file name for the ProxyDHCP to chainload iPXE correctly
    # iPXE first loads ipxe.efi via TFTP.
    # Then ipxe.efi sends another DHCP request (with Option 77 = "iPXE").
    # We must detect this and send it the boot.ipxe script via HTTP instead.

    # Wait, pypxe's TFTP and HTTP are simple.
    # Let's refine the ProxyDHCP logic to handle the iPXE chainloading.

    tftp = TFTPServer(server_ip)
    # The HTTP server serves the current directory to allow access to /isos and /netboot
    # This is required for iPXE to find boot.ipxe and the ISO files.
    http = HTTPServer("0.0.0.0", 80, ".")
    pdhcp = ProxyDHCP(interface_name, server_ip, "ipxe.efi")

    tftp.start()
    http.start()

    print("\nServices are running!")
    print(f"Server IP: {server_ip}")
    print(f"ISO Directory: {os.path.abspath(iso_dir)}")
    print("Press Ctrl+C to stop the server.\n")

    try:
        pdhcp.start() # This is blocking
    except KeyboardInterrupt:
        print("\nShutting down...")
        pdhcp.stop()
        # Other threads are daemonized and will exit with main

if __name__ == "__main__":
    main()
