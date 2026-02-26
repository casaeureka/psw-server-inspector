"""System information detection module"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server_inspector.utils import PSUTIL_AVAILABLE, run_command

if PSUTIL_AVAILABLE:
    import psutil


class SystemDetector:
    """Detect system information"""

    @staticmethod
    def detect() -> dict[str, Any]:
        """Detect system/chassis information."""
        system_data: dict[str, Any] = {}

        system_data["boot_mode"] = "UEFI" if Path("/sys/firmware/efi").exists() else "Legacy BIOS"

        if Path("/sys/firmware/efi").exists():
            mokutil_output = run_command(["mokutil", "--sb-state"])
            secureboot = ""
            for line in mokutil_output.split("\n"):
                if "SecureBoot" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        secureboot = parts[1]
                    break
            if secureboot:
                system_data["secure_boot"] = secureboot
            else:
                # Alternative method - check SecureBoot EFI variable
                try:
                    efi_vars_path = Path("/sys/firmware/efi/efivars")
                    secureboot_files = list(efi_vars_path.glob("SecureBoot-*"))
                    if secureboot_files:
                        data = secureboot_files[0].read_bytes()
                        if data:
                            last_byte = data[-1]
                            if last_byte == 1:
                                system_data["secure_boot"] = "enabled"
                            elif last_byte == 0:
                                system_data["secure_boot"] = "disabled"
                except (OSError, IndexError):
                    pass

        try:
            tpm_devs = list(Path("/dev").glob("tpm*"))
            if tpm_devs:
                system_data["tpm_present"] = True
                tpm_version_path = Path("/sys/class/tpm/tpm0/tpm_version_major")
                if tpm_version_path.exists():
                    try:
                        tpm_version = tpm_version_path.read_text().strip()
                        if tpm_version:
                            system_data["tpm_version"] = f"{tpm_version}.0"
                    except OSError:
                        pass
        except OSError:
            pass

        system_data["hostname"] = run_command(["hostname"])
        system_data["kernel"] = run_command(["uname", "-r"])

        os_name = "Unknown"
        try:
            os_release_path = Path("/etc/os-release")
            if os_release_path.exists():
                os_release_content = os_release_path.read_text()
                for line in os_release_content.split("\n"):
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip('"')
                        break
        except OSError:
            pass
        system_data["os"] = os_name

        if PSUTIL_AVAILABLE:
            boot_time = psutil.boot_time()
            system_data["boot_time"] = datetime.fromtimestamp(boot_time, tz=UTC).isoformat()

        return system_data
