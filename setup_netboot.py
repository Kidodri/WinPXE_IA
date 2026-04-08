import urllib.request
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('Netboot-Setup')

NETBOOT_DIR = 'netboot'

# URLs des chargeurs d'amorçage officiels iPXE (pré-compilés)
BOOTLOADERS = {
    'ipxe.efi': 'https://boot.ipxe.org/ipxe.efi',           # UEFI x64
    'undionly.kpxe': 'https://boot.ipxe.org/undionly.kpxe', # BIOS Legacy
    'ipxe_ia32.efi': 'https://boot.ipxe.org/ipxe-ia32.efi'  # UEFI x86
}

def setup():
    if not os.path.exists(NETBOOT_DIR):
        os.makedirs(NETBOOT_DIR)
        logger.info(f"Dossier '{NETBOOT_DIR}' créé.")

    # 1. Téléchargement des bootloaders
    for filename, url in BOOTLOADERS.items():
        filepath = os.path.join(NETBOOT_DIR, filename)
        if not os.path.exists(filepath):
            logger.info(f"Téléchargement de {filename} depuis {url}...")
            try:
                urllib.request.urlretrieve(url, filepath)
                logger.info(f"OK : {filename} sauvegardé.")
            except Exception as e:
                logger.error(f"Erreur lors du téléchargement de {filename}: {e}")
        else:
            logger.info(f"Le fichier {filename} existe déjà.")

    # 2. Création d'un script iPXE d'exemple (boot.ipxe)
    # Ce script sera appelé par iPXE après son chargement initial.
    boot_ipxe_content = """#!ipxe

# Menu iPXE d'exemple
# -------------------------------------------------------------------------
# Ce script est chargé via HTTP par iPXE une fois que le réseau est initialisé.

set server_ip 192.168.1.100  # <--- REMPLACEZ PAR VOTRE IP

:start
menu WinPXE Boot Menu
item --gap --             -----------------------------------------
item install_windows      Installer Windows (via WinPE/ISO)
item shell                Lancer le shell iPXE
item reboot               Redémarrer l'ordinateur
item --gap --             -----------------------------------------
choose --default install_windows --timeout 10 target && goto ${target}

:install_windows
echo Chargement de l'installateur Windows...
# Pour booter une image ISO directement (via HTTP) :
# sanboot http://${server_ip}/images/windows_install.iso
#
# Pour booter WinPE (fichiers extraits) :
# kernel http://${server_ip}/winpe/boot/boot.sdi
# initrd http://${server_ip}/winpe/sources/boot.wim
# boot
goto start

:shell
shell
goto start

:reboot
reboot
"""
    boot_ipxe_path = os.path.join(NETBOOT_DIR, 'boot.ipxe')
    if not os.path.exists(boot_ipxe_path):
        with open(boot_ipxe_path, 'w') as f:
            f.write(boot_ipxe_content)
        logger.info(f"Fichier d'exemple 'boot.ipxe' créé dans '{NETBOOT_DIR}'.")

if __name__ == "__main__":
    logger.info("Configuration de l'environnement de boot réseau...")
    setup()
    logger.info("Terminé. Vous pouvez maintenant lancer 'python server.py'.")
