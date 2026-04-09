from pypxe import tftp
import threading
import os

class TFTPServer:
    def __init__(self, ip, port=69, netboot_dir="netboot"):
        self.ip = ip
        self.port = port
        self.netboot_dir = netboot_dir
        self.server = None
        self.thread = None

    def start(self):
        print(f"Starting TFTP Server on {self.ip}:{self.port} serving {self.netboot_dir}...")
        self.server = tftp.TFTPD(ip=self.ip, port=self.port, netboot_directory=self.netboot_dir)
        self.thread = threading.Thread(target=self.server.listen)
        self.thread.daemon = True
        self.thread.start()

if __name__ == "__main__":
    import time
    server = TFTPServer("0.0.0.0")
    server.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping TFTP...")
