# WinPXE Python Server - Documentation

## Usage
1. Place your `.iso` files in the `isos/` folder.
2. Run `python winpxe.py` with Administrator/Elevated privileges.
3. Select your network interface.
4. Boot your client PC via UEFI Network Boot (IPv4).

## Windows ISO Notes
This server uses `sanboot --mem` to boot ISO files. This means:
- The **entire ISO** is downloaded into the client's RAM before it starts.
- Your client must have enough RAM (ISO size + ~2GB for the OS).
- If the Windows Installer starts but says "A media driver your computer needs is missing", it means the virtual CD-ROM was lost.
- **Workaround**: For complex Windows installations, it is recommended to use a WinPE environment that mounts the Windows installation files via an SMB (Windows Share).

## Requirements
- Python 3.7+
- Scapy (`pip install scapy`)
- Psutil (`pip install psutil`)
- Requests (`pip install requests`)
- Npcap (required by Scapy on Windows)
