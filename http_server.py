import http.server
import socketserver
import threading
import os
import logging

logger = logging.getLogger("WinPXE-Server")

class HTTPServer:
    def __init__(self, ip, port=80, directory="."):
        self.ip = ip
        self.port = port
        self.directory = directory
        self.httpd = None
        self.thread = None

    def start(self):
        # Use the directory argument in SimpleHTTPRequestHandler (Python 3.7+)
        directory = os.path.abspath(self.directory)
        handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=directory, **kwargs)

        # Allow reuse of address
        socketserver.TCPServer.allow_reuse_address = True
        self.httpd = socketserver.TCPServer((self.ip, self.port), handler)

        print(f"Starting HTTP Server on {self.ip}:{self.port} serving {directory}...")
        self.thread = threading.Thread(target=self.httpd.serve_forever)
        self.thread.daemon = True
        self.thread.start()

def generate_ipxe_menu(iso_dir, server_ip, http_port):
    isos = [f for f in os.listdir(iso_dir) if f.lower().endswith(".iso")]
    extract_base = "netboot/extracted"

    menu = "#!ipxe\n\n"
    # Ensure console is in a clean state. We avoid 'usb-keyboard' as it
    # conflicts with native UEFI drivers.
    menu += "console --keep\n"
    menu += "set menu-timeout 30000\n"
    menu += "set menu-default iso_0\n\n"

    menu += ":start\n"
    menu += "menu WinPXE Boot Menu (Use number keys 0-9 if arrows fail)\n"
    menu += "item --gap --             ------------------------- ISO Images -------------------------\n"

    for i, iso in enumerate(isos):
        # Add numeric hotkeys for the first 10 ISOs
        key = f" --key {i}" if i < 10 else ""
        menu += f"item{key} iso_{i} {iso}\n"

    menu += "item --gap --             ------------------------- Settings ---------------------------\n"
    menu += "item --key s shell iPXE shell\n"
    menu += "item --key x exit  Exit and continue booting\n\n"

    menu += "choose --timeout ${menu-timeout} --default ${menu-default} target && goto ${target}\n\n"

    for i, iso in enumerate(isos):
        menu += f":iso_{i}\n"
        menu += f"echo Booting {iso}...\n"

        # Check if this is a processed Windows ISO
        safe_name = os.path.splitext(iso)[0].replace(" ", "_").replace(".", "_")
        wim_path = os.path.join(extract_base, safe_name, "boot.wim")

        if os.path.exists(wim_path):
            logger.info(f"Generating automated wimboot entry for {iso}")

            # Generate the startup script for this ISO
            # We use 'ping' instead of 'timeout' because 'timeout' is often missing in WinPE
            startup_script = f"""@echo off
echo ========================================================
echo   WinPXE Automated Windows Installation
echo ========================================================
echo.
echo Waiting for network initialization...
wpeinit

:retry
echo Attempting to mount SMB share: \\\\{server_ip}\\WinPXE_ISOs
net use Z: \\\\{server_ip}\\WinPXE_ISOs >nul 2>&1

if errorlevel 1 (
    echo.
    echo [!] Failed to connect to server (Error Code: %errorlevel%).
    echo.
    echo If 'Password Protected Sharing' is enabled, please enter your credentials.
    set /p "PXE_USER=Username: "
    set /p "PXE_PASS=Password: "

    echo Retrying with credentials...
    net use Z: \\\\{server_ip}\\WinPXE_ISOs "%PXE_PASS%" /user:"%PXE_USER%" >nul 2>&1
)

if errorlevel 1 (
    echo.
    echo [!] Still failed to connect. Retrying in 5 seconds...
    echo.
    echo     Debugging Tips:
    echo     - Ensure the host firewall allows File and Printer Sharing.
    echo     - Ensure the host network profile is set to 'Private'.
    echo.
    ping -n 6 127.0.0.1 >nul
    goto retry
)

echo [OK] Connected to server.
echo [OK] Launching Setup for {iso}...
Z:\\extracted\\{safe_name}\\setup.exe
"""
            script_path = os.path.join(extract_base, safe_name, "winpxe_startup.bat")
            with open(script_path, "w") as f:
                f.write(startup_script)

            # Generate winpeshl.ini to trigger the script
            # Note: winpeshl.ini looks for apps in Windows\System32 by default
            # We will inject our script there.
            ini_content = f'[LaunchApps]\n"X:\\Windows\\System32\\winpxe_startup.bat"\n'
            ini_path = os.path.join(extract_base, safe_name, "winpeshl.ini")
            with open(ini_path, "w") as f:
                f.write(ini_content)

            ext_dir = f"http://{server_ip}:{http_port}/netboot/extracted/{safe_name}"
            menu += "echo Optimized Windows Boot detected (Automated)...\n"
            menu += f"kernel http://{server_ip}:{http_port}/netboot/wimboot\n"
            menu += f"initrd {ext_dir}/bootmgfw.efi bootmgfw.efi\n"
            menu += f"initrd {ext_dir}/bcd bcd\n"
            menu += f"initrd {ext_dir}/boot.sdi boot.sdi\n"
            menu += f"initrd {ext_dir}/boot.wim boot.wim\n"
            # Injecting into Windows/System32 allows WinPE to find them automatically
            menu += f"initrd {ext_dir}/winpeshl.ini Windows/System32/winpeshl.ini\n"
            menu += f"initrd {ext_dir}/winpxe_startup.bat Windows/System32/winpxe_startup.bat\n"
            menu += "boot\n"
        else:
            if "win" in iso.lower():
                menu += "echo Windows ISO detected but not processed. Falling back to 'sanboot'...\n"
                menu += "echo Note: This will likely fail to find media drivers.\n"
            # Using sanboot for general ISOs (removed --mem for better compatibility)
            menu += f"sanboot http://{server_ip}:{http_port}/isos/{iso}\n"

        menu += "goto start\n\n"

    menu += ":shell\n"
    menu += "shell\n"
    menu += "goto start\n\n"

    menu += ":exit\n"
    menu += "exit\n"

    os.makedirs("netboot", exist_ok=True)
    with open("netboot/boot.ipxe", "w") as f:
        f.write(menu)
    print("Generated netboot/boot.ipxe")

if __name__ == "__main__":
    import time
    generate_ipxe_menu("isos", "127.0.0.1", 80)
    server = HTTPServer("0.0.0.0", 80, ".")
    server.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping HTTP...")
