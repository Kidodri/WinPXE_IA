import os
import sys
import time
import subprocess
import logging
import secrets
import string
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

def create_temp_user(username):
    # Generate a secure 16-character password
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for i in range(16))

    logger.info(f"Creating temporary Windows user: {username}")

    # Delete user if it already exists (from a previous crash)
    subprocess.run(["net", "user", username, "/delete"], capture_output=True)

    # Create the user
    result = subprocess.run(["net", "user", username, password, "/add", "/expires:never", "/passwordchg:no"], capture_output=True, text=True)

    if result.returncode == 0:
        # Hide the user from the login screen (optional but cleaner)
        reg_path = f"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\SpecialAccounts\\UserList"
        subprocess.run(["reg", "add", reg_path, "/v", username, "/t", "REG_DWORD", "/d", "0", "/f"], capture_output=True)
        return password
    else:
        logger.error(f"Failed to create temporary user: {result.stderr.strip()}")
        return None

def delete_temp_user(username):
    logger.info(f"Deleting temporary Windows user: {username}")
    subprocess.run(["net", "user", username, "/delete"], capture_output=True)
    reg_path = f"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\SpecialAccounts\\UserList"
    subprocess.run(["reg", "delete", reg_path, "/v", username, "/f"], capture_output=True)

def setup_smb_share(iso_dir, username):
    share_name = "WinPXE_ISOs"
    abs_path = os.path.abspath(iso_dir)

    logger.info(f"Setting up SMB share for {abs_path}...")

    # 1. Apply NTFS permissions (Icacls)
    # (OI)(CI)R = Object Inherit, Container Inherit, Read
    logger.info(f"Granting NTFS read permissions to {username}...")
    subprocess.run(["icacls", abs_path, "/grant", f"{username}:(OI)(CI)R"], capture_output=True)

    # 2. Setup the Share
    # Try to remove existing share first
    subprocess.run(["net", "share", share_name, "/delete"], capture_output=True)

    # Create the share and grant the temp user READ access
    # We also keep Everyone,READ for maximum compatibility, but the temp user is our primary target
    result = subprocess.run(["net", "share", f"{share_name}=\"{abs_path}\"", f"/grant:{username},READ", "/grant:Everyone,READ"], capture_output=True, text=True)

    if result.returncode == 0:
        logger.info(f"SMB Share '{share_name}' created successfully.")
        return True
    else:
        logger.error(f"Failed to create SMB share: {result.stderr.strip()}")
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

    # 4. Create Temporary User for SMB
    temp_username = "WinPXE_User"
    temp_password = create_temp_user(temp_username)
    if not temp_password:
        logger.error("Could not create temporary user. Authentication might fail in WinPE.")
        temp_username = "Guest" # Fallback
        temp_password = ""

    # 5. Setup SMB Share
    setup_smb_share(iso_dir, temp_username)

    # 6. Generate iPXE Menu (Now passes credentials)
    generate_ipxe_menu(iso_dir, server_ip, 80, smb_user=temp_username, smb_pass=temp_password)

    # 7. Start Servers
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
    logger.info(f"A temporary user '{temp_username}' has been created to handle SMB authentication.")
    logger.info("This allows Windows installation even if 'Password protected sharing' is ON.")
    logger.info("---")
    logger.info("Ready for client connections. Press Ctrl+C to stop.")

    try:
        pdhcp.start() # This is blocking
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        pdhcp.stop()
        # Clean up share and user on exit
        subprocess.run(["net", "share", "WinPXE_ISOs", "/delete"], capture_output=True)
        if temp_username != "Guest":
            delete_temp_user(temp_username)

if __name__ == "__main__":
    main()
