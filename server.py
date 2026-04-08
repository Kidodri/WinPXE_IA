import threading
import logging
import os
import sys
from winpxe_dhcp import WinPXEDHCPD
from pypxe.tftp import TFTPD
from pypxe.http import HTTPD

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('WinPXE-Server')

# Configuration du serveur
SERVER_IP = '192.168.1.100'  # À ADAPTER à l'IP de votre machine
NETBOOT_DIR = 'netboot'      # Dossier contenant les fichiers de boot (ipxe.efi, etc.)

# Création du dossier netboot s'il n'existe pas
if not os.path.exists(NETBOOT_DIR):
    os.makedirs(NETBOOT_DIR)
    logger.info(f"Dossier '{NETBOOT_DIR}' créé. Veuillez y placer vos fichiers de boot (ipxe.efi).")

def start_dhcp():
    logger.info("Démarrage du ProxyDHCP (Scapy)...")
    dhcp_server = WinPXEDHCPD(
        ip=SERVER_IP,
        file_server=SERVER_IP,
        mode_proxy=True,
        mode_verbose=True
    )
    dhcp_server.listen()

def start_tftp():
    logger.info("Démarrage du serveur TFTP...")
    tftp_server = TFTPD(
        ip=SERVER_IP,
        netboot_directory=NETBOOT_DIR,
        mode_verbose=True
    )
    tftp_server.listen()

def start_http():
    logger.info("Démarrage du serveur HTTP...")
    http_server = HTTPD(
        ip=SERVER_IP,
        netboot_directory=NETBOOT_DIR,
        mode_verbose=True
    )
    http_server.listen()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        SERVER_IP = sys.argv[1]

    logger.info(f"=== WinPXE Server starting on {SERVER_IP} ===")

    # Lancement des threads
    threads = []
    threads.append(threading.Thread(target=start_dhcp, daemon=True))
    threads.append(threading.Thread(target=start_tftp, daemon=True))
    threads.append(threading.Thread(target=start_http, daemon=True))

    for t in threads:
        t.start()

    logger.info("Tous les services sont lancés. Appuyez sur Ctrl+C pour arrêter.")

    try:
        while True:
            for t in threads:
                if not t.is_alive():
                    logger.error("Un service s'est arrêté inopinément !")
                    sys.exit(1)
            t.join(1)
    except KeyboardInterrupt:
        logger.info("Arrêt du serveur...")
