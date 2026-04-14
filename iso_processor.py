import os
import subprocess
import shutil
import logging

logger = logging.getLogger("WinPXE-Server")

class ISOProcessor:
    def __init__(self, iso_dir="isos", extract_dir="netboot/extracted"):
        self.iso_dir = iso_dir
        self.extract_dir = os.path.abspath(extract_dir)

    def process_all(self):
        if not os.path.exists(self.iso_dir):
            logger.info(f"ISO directory '{self.iso_dir}' not found. Skipping ISO processing.")
            return

        isos = [f for f in os.listdir(self.iso_dir) if f.lower().endswith(".iso")]
        if not isos:
            logger.info("No ISO files found in the 'isos' directory.")
            return

        for iso in isos:
            self.process_iso(iso)

    def get_safe_name(self, iso_name):
        return os.path.splitext(iso_name)[0].replace(" ", "_").replace(".", "_")

    def process_iso(self, iso_name):
        iso_path = os.path.abspath(os.path.join(self.iso_dir, iso_name))
        safe_name = self.get_safe_name(iso_name)
        target_dir = os.path.join(self.extract_dir, safe_name)

        full_extract_base = os.path.join(self.iso_dir, "extracted")
        iso_extract_path = os.path.join(full_extract_base, safe_name)

        if os.path.exists(target_dir) and os.path.exists(iso_extract_path):
            if os.path.exists(os.path.join(target_dir, "boot.wim")):
                logger.info(f"ISO '{iso_name}' already fully processed.")
                return

        logger.info(f"Attempting to process Windows ISO: {iso_name}")

        # PowerShell script to mount, copy specific files, and dismount
        # We look for: efi/boot/bootx64.efi (renamed to bootmgfw.efi), boot/bcd, boot/boot.sdi, sources/boot.wim
        ps_script = f"""
$ErrorActionPreference = "Stop"
try {{
    $isoPath = @'
{iso_path}
'@
    $targetDir = @'
{target_dir}
'@

    Write-Host "Mounting ISO: $isoPath"
    $mountResult = Mount-DiskImage -ImagePath $isoPath -PassThru
    $driveLetter = ($mountResult | Get-Volume).DriveLetter
    if (-not $driveLetter) {{
        throw "Failed to get drive letter for mounted ISO."
    }}
    $drivePath = "$($driveLetter):\\"
    Write-Host "Mounted on drive $drivePath"

    if (-not (Test-Path $targetDir)) {{
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }}

    $filesToCopy = @(
        "efi/boot/bootx64.efi",
        "boot/bcd",
        "boot/boot.sdi",
        "sources/boot.wim"
    )

    foreach ($file in $filesToCopy) {{
        $sourceFile = Join-Path $drivePath $file
        if (Test-Path $sourceFile) {{
            $destName = Split-Path $file -Leaf
            if ($destName -eq "bootx64.efi") {{ $destName = "bootmgfw.efi" }}
            $destFile = Join-Path $targetDir $destName
            Write-Host "Copying $file to $destFile"
            Copy-Item -Path $sourceFile -Destination $destFile -Force
        }} else {{
            if ($file -eq "efi/boot/bootx64.efi") {{
                # Try alternative location for bootmgfw.efi
                $altSource = Join-Path $drivePath "sources/bootmgfw.efi"
                if (Test-Path $altSource) {{
                    $destFile = Join-Path $targetDir "bootmgfw.efi"
                    Write-Host "Copying $altSource to $destFile"
                    Copy-Item -Path $altSource -Destination $destFile -Force
                    continue
                }}
            }}
            Write-Warning "Required file not found on ISO: $file"
        }}
    }}

    Write-Host "Performing full extraction to allow SMB installation..."
    $isoExtractPath = @'
{iso_extract_path}
'@

    if (-not (Test-Path $isoExtractPath)) {{
        New-Item -ItemType Directory -Path $isoExtractPath -Force | Out-Null
        Write-Host "Copying all files from ISO to $isoExtractPath (this may take a few minutes)..."
        Copy-Item -Path "$drivePath*" -Destination $isoExtractPath -Recurse -Force
    }} else {{
        Write-Host "Full extraction already exists at $isoExtractPath"
    }}

    Write-Host "Dismounting ISO..."
    Dismount-DiskImage -ImagePath $isoPath
    Write-Host "Success"
}} catch {{
    Write-Error $_.Exception.Message
    if (Get-DiskImage -ImagePath $isoPath) {{
        Dismount-DiskImage -ImagePath $isoPath
    }}
    exit 1
}}
"""

        try:
            # We run this on Windows. Stream output in real-time.
            process = subprocess.Popen(
                ["powershell", "-Command", ps_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            success = False
            for line in process.stdout:
                line = line.strip()
                if line:
                    logger.info(f"[{iso_name}] {line}")
                    if line == "Success":
                        success = True

            process.wait()

            if process.returncode == 0 and success:
                logger.info(f"Extraction successful for {iso_name}.")
            else:
                logger.error(f"PowerShell failed for {iso_name} (Code: {process.returncode}). Cleaning up...")
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)

        except FileNotFoundError:
            logger.error("PowerShell not found. ISO processing requires Windows with PowerShell.")
        except Exception as e:
            logger.error(f"Unexpected error processing {iso_name}: {e}")

if __name__ == "__main__":
    # Setup basic logging for standalone test
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    proc = ISOProcessor()
    proc.process_all()
