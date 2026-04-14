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

def user_exists(username):
    try:
        result = subprocess.run(["net", "user", username], capture_output=True, timeout=10)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout while checking for user '{username}'.")
        return False

def create_temp_user(username):
    # Generate a secure 16-character password
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for i in range(16))

    try:
        if user_exists(username):
            logger.info(f"User '{username}' already exists. Updating password...")
            # Just update password for existing user
            result = subprocess.run(["net", "user", username, password], capture_output=True, text=True, timeout=30)
        else:
            logger.info(f"Creating new temporary Windows user: {username}")
            # Create the user
            result = subprocess.run(["net", "user", username, password, "/add", "/expires:never", "/passwordchg:no"], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout while creating/updating user '{username}'.")
        return None

    if result.returncode == 0:
        # Hide the user from the login screen (optional but cleaner)
        logger.debug(f"Hiding user '{username}' from login screen...")
        reg_path = f"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\SpecialAccounts\\UserList"
        subprocess.run(["reg", "add", reg_path, "/v", username, "/t", "REG_DWORD", "/d", "0", "/f"], capture_output=True)
        return password
    else:
        logger.error(f"Failed to manage temporary user: {result.stderr.strip()}")
        return None

def delete_temp_user(username):
    if user_exists(username):
        logger.info(f"Deleting temporary Windows user: {username}")
        subprocess.run(["net", "user", username, "/delete"], capture_output=True)
        reg_path = f"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\SpecialAccounts\\UserList"
        subprocess.run(["reg", "delete", reg_path, "/v", username, "/f"], capture_output=True)

def cleanup_smb_resources():
    share_name = "WinPXE_ISOs"
    logger.info("Cleaning up previous SMB resources...")
    # Delete share first to unlock any files/user hooks
    try:
        subprocess.run(["net", "share", share_name, "/delete"], capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        logger.warning("Timeout while deleting share. It might be in use.")

def setup_smb_share(iso_dir, username):
    share_name = "WinPXE_ISOs"
    abs_path = os.path.abspath(iso_dir)

    logger.info(f"Setting up SMB share for {abs_path}...")

    # 1. Apply NTFS permissions (Icacls)
    # (OI)(CI)R = Object Inherit, Container Inherit, Read
    logger.info(f"Ensuring NTFS read permissions for {username}...")
    # We use /grant:r to replace existing permissions for this user if they exist
    result = subprocess.run(["icacls", abs_path, "/grant:r", f"{username}:(OI)(CI)R"], capture_output=True)
    if result.returncode != 0:
        logger.warning(f"Icacls warning: {result.stderr.decode().strip()}")

    # 2. Setup the Share
    # Create the share and grant the temp user READ access
    # We also keep Everyone,READ for maximum compatibility
    logger.info(f"Creating network share '{share_name}'...")
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

    # 2. SMB Cleanup (Essential before user management)
    cleanup_smb_resources()

    # 3. Select Interface
    iface = select_interface()
    if not iface:
        sys.exit(1)

    server_ip = iface['ip']
    interface_name = iface['name']

    # 4. Process ISOs
    iso_dir = "isos"
    if not os.path.exists(iso_dir):
        os.makedirs(iso_dir)

    processor = ISOProcessor(iso_dir=iso_dir)
    processor.process_all()

    # 5. Create Temporary User for SMB
    temp_username = "WinPXE_User"
    temp_password = create_temp_user(temp_username)
    if not temp_password:
        logger.error("Could not create temporary user. Authentication might fail in WinPE.")
        temp_username = "Guest" # Fallback
        temp_password = ""

    # 6. Setup SMB Share
    setup_smb_share(iso_dir, temp_username)

    # 7. Generate iPXE Menu (Now passes credentials)
    generate_ipxe_menu(iso_dir, server_ip, 80, smb_user=temp_username, smb_pass=temp_password)

    # 8. Start Servers
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
        cleanup_smb_resources()
        if temp_username != "Guest":
            delete_temp_user(temp_username)

if __name__ == "__main__":
    main()
