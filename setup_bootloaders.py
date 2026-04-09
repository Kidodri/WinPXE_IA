import requests
import os

def download_file(url, dest):
    print(f"Downloading {url} to {dest}...")
    try:
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print("Download complete.")
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False

def ensure_bootloaders():
    os.makedirs("netboot", exist_ok=True)
    files = {
        "netboot/ipxe.efi": "https://boot.ipxe.org/x86_64-efi/ipxe.efi",
        "netboot/wimboot": "https://github.com/ipxe/wimboot/releases/latest/download/wimboot"
    }

    for dest, url in files.items():
        if not os.path.exists(dest):
            download_file(url, dest)

if __name__ == "__main__":
    ensure_bootloaders()
