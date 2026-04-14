import http.server
import socketserver
import threading
import os

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

    menu = "#!ipxe\n\n"
    # Ensure console is initialized, can help with keyboard issues
    menu += "console\n"
    menu += "set menu-timeout 30000\n"
    menu += "set menu-default iso_0\n\n"

    menu += ":start\n"
    menu += "menu WinPXE Boot Menu\n"
    menu += "item --gap --             ------------------------- ISO Images -------------------------\n"

    for i, iso in enumerate(isos):
        menu += f"item iso_{i} {iso}\n"

    menu += "item --gap --             ------------------------- Settings ---------------------------\n"
    menu += "item shell iPXE shell\n"
    menu += "item exit  Exit and continue booting\n\n"

    menu += "choose --timeout ${menu-timeout} --default ${menu-default} target && goto ${target}\n\n"

    for i, iso in enumerate(isos):
        menu += f":iso_{i}\n"
        menu += f"echo Booting {iso}...\n"
        if "win" in iso.lower():
            menu += "echo Windows ISO detected. Loading via 'sanboot --mem'...\n"
            menu += "echo Note: Large Windows ISOs require significant RAM (ISO size + 2GB).\n"
            menu += "echo If the installer asks for drivers or cannot find a disk,\n"
            menu += "echo consider using a WinPE-based approach with an SMB share.\n"
        # Using sanboot --mem for general ISOs
        menu += f"sanboot --mem http://{server_ip}:{http_port}/isos/{iso}\n"
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
