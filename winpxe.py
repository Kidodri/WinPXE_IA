import os
import sys
import time
import subprocess
import logging
from interface_selector import select_interface
from proxydhcp import ProxyDHCP
from tftp_server import TFTPServer
from http_server import HTTPServer, generate_ipxe_menu
from iso_processor import ISOProcessor

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("WinPXE-Server")

def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        # Fallback for non-windows (though this app is windows-centric)
        return os.getuid() == 0 if hasattr(os, 'getuid') else False

def setup_smb_share(iso_dir):
    share_name = "WinPXE_ISOs"
    abs_path = os.path.abspath(iso_dir)

    logger.info(f"Setting up SMB share for {abs_path}...")

    # Try to remove existing share first (just in case)
    subprocess.run(["net", "share", share_name, "/delete"], capture_output=True)

    # Create the share
    # /grant:Everyone,READ gives read permission to everyone
    # Use quotes around the path for safety
    result = subprocess.run(["net", "share", f"{share_name}=\"{abs_path}\"", "/grant:Everyone,READ"], capture_output=True, text=True)

    if result.returncode == 0:
        logger.info(f"SMB Share '{share_name}' created successfully.")
        return True
    else:
        logger.error(f"Failed to create SMB share: {result.stderr.strip()}")
        # Check if it failed because it already exists (if delete failed for some reason)
        if "already shared" in result.stderr:
             logger.info(f"SMB Share '{share_name}' already exists.")
             return True
        return False

def main():
    logger.info("=== WinPXE Python Server ===")

    if not is_admin():
        logger.error("!!! FATAL ERROR: WinPXE must be run as Administrator !!!")
        logger.error("Raw socket operations and SMB sharing require elevated privileges.")
        input("Press Enter to exit...")
        sys.exit(1)

    # 1. Check for bootloaders
    import setup_bootloaders
    setup_bootloaders.ensure_bootloaders()

    # 2. Select Interface
    iface = select_interface()
    if not iface:
        sys.exit(1)

    server_ip = iface['ip']
    interface_name = iface['name']

    # 3. Process ISOs
    iso_dir = "isos"
    if not os.path.exists(iso_dir):
        os.makedirs(iso_dir)

    processor = ISOProcessor(iso_dir=iso_dir)
    processor.process_all()

    # 4. Setup SMB Share
    setup_smb_share(iso_dir)

    # 5. Generate iPXE Menu
    generate_ipxe_menu(iso_dir, server_ip, 80)

    # 6. Start Servers
    tftp = TFTPServer(server_ip)
    http = HTTPServer("0.0.0.0", 80, ".")
    pdhcp = ProxyDHCP(interface_name, server_ip, "ipxe.efi")

    tftp.start()
    http.start()

    logger.info("=== Services are running! ===")
    logger.info(f"Server IP: {server_ip}")
    logger.info(f"ISO Directory: {os.path.abspath(iso_dir)}")
    logger.info(f"SMB Share Path: \\\\{server_ip}\\WinPXE_ISOs")
    logger.info("---")
    logger.info("IMPORTANT FOR WINDOWS INSTALLATION:")
    logger.info("1. Ensure 'Password protected sharing' is TURNED OFF in Windows settings.")
    logger.info("   (Control Panel > Network and Sharing Center > Advanced sharing settings)")
    logger.info("2. If the client fails to connect, try the 'Guest' account or check folder permissions.")
    logger.info("---")
    logger.info("Ready for client connections. Press Ctrl+C to stop.")

    try:
        pdhcp.start() # This is blocking
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        pdhcp.stop()
        # Clean up share on exit (optional, but good practice)
        subprocess.run(["net", "share", "WinPXE_ISOs", "/delete"], capture_output=True)

if __name__ == "__main__":
    main()
