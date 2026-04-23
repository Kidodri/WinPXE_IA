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

def cleanup_smb_resources():
    share_name = "WinPXE_ISOs"
    logger.info("Cleaning up previous SMB resources...")
    # Delete share first to unlock any files/user hooks
    try:
        subprocess.run(["net", "share", share_name, "/delete"], capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        logger.warning("Timeout while deleting share. It might be in use.")

def get_localized_everyone():
    """Returns the localized name for the 'Everyone' group using PowerShell."""
    try:
        # Use SID S-1-1-0 to find the localized name
        ps_cmd = "(New-Object System.Security.Principal.SecurityIdentifier('S-1-1-0')).Translate([System.Security.Principal.NTAccount]).Value"
        result = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            name = result.stdout.strip()
            if name:
                return name
    except Exception as e:
        logger.debug(f"Failed to get localized 'Everyone' name: {e}")
    return "Everyone" # Fallback

def setup_smb_share(iso_dir):
    share_name = "WinPXE_ISOs"
    abs_path = os.path.abspath(iso_dir)
    everyone_name = get_localized_everyone()

    logger.info(f"Setting up SMB share for {abs_path}...")

    # 1. Apply NTFS permissions (Icacls)
    # We use the SID *S-1-1-0 for Everyone to be language-independent in icacls
    # (OI)(CI)R = Object Inherit, Container Inherit, Read
    # /T = Recursive (important for extracted ISO content)
    logger.info(f"Ensuring NTFS read permissions for {everyone_name} (SID: *S-1-1-0) recursively...")
    result = subprocess.run(["icacls", abs_path, "/grant:r", "*S-1-1-0:(OI)(CI)R", "/T"], capture_output=True)
    if result.returncode != 0:
        logger.warning(f"Icacls warning: {result.stderr.decode('cp850', errors='replace').strip()}")

    # 2. Setup the Share
    # Create the share and grant Everyone READ access
    # We remove manual quotes from the path as subprocess.run handles it
    logger.info(f"Creating network share '{share_name}' granting access to '{everyone_name}'...")
    result = subprocess.run(["net", "share", f"{share_name}={abs_path}", f"/grant:{everyone_name},READ"], capture_output=True, text=True)

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

    # 5. Setup SMB Share
    setup_smb_share(iso_dir)

    # 6. Generate iPXE Menu
    generate_ipxe_menu(iso_dir, server_ip, 80)

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
    logger.info("If the installation hangs or fails to mount the share:")
    logger.info("1. Ensure your Network Profile is set to 'Private' (not Public).")
    logger.info("2. Ensure Windows Firewall allows 'File and Printer Sharing'.")
    logger.info("3. If 'Password protected sharing' is ON, enter your credentials in WinPE.")
    logger.info("---")
    logger.info("Ready for client connections. Press Ctrl+C to stop.")

    try:
        pdhcp.start() # This is blocking
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        pdhcp.stop()
        # Clean up share on exit
        cleanup_smb_resources()

if __name__ == "__main__":
    main()
