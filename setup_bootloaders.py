import requests
import os
import logging

logger = logging.getLogger("WinPXE-Server")

def download_file(url, dest):
    logger.info(f"Downloading {url} to {dest}...")
    try:
        response = requests.get(url, stream=True, timeout=15)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(dest, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0 and downloaded % (1024 * 1024) < 8192: # Log every ~1MB
                        logger.debug(f"Progress: {downloaded}/{total_size} bytes ({(downloaded/total_size)*100:.1f}%)")

        logger.info(f"Successfully downloaded {dest}.")
        return True
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return False

def ensure_bootloaders():
    os.makedirs("netboot", exist_ok=True)
    files = {
        "netboot/ipxe.efi": "https://boot.ipxe.org/x86_64-efi/ipxe.efi",
        "netboot/wimboot": "https://github.com/ipxe/wimboot/releases/latest/download/wimboot"
    }

    for dest, url in files.items():
        if not os.path.exists(dest):
            logger.info(f"Bootloader '{dest}' missing.")
            download_file(url, dest)
        else:
            logger.info(f"Bootloader '{dest}' is already present.")

if __name__ == "__main__":
    ensure_bootloaders()
