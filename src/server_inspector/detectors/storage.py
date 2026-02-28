"""Storage detection module"""

import contextlib
import logging
import re
from pathlib import Path
from typing import Any

from server_inspector.utils import (
    MB_PER_GB,
    PB_TO_TB_MULTIPLIER,
    TB_TO_GB_MULTIPLIER,
    is_root,
    run_command,
    sanitize_device_name,
)

DEFAULT_BLOCK_SIZE = 512


class StorageDetector:
    """Detect storage devices and recommend pool assignments"""

    @staticmethod
    def _is_usb_device(name: str) -> bool:
        """Check if a block device is on the USB bus."""
        try:
            by_id_dir = Path("/dev/disk/by-id")
            if by_id_dir.exists():
                for entry in by_id_dir.iterdir():
                    if entry.is_symlink():
                        target = str(entry.resolve())
                        if target.endswith(name) and "usb" in entry.name.lower():
                            return True
        except OSError:
            pass
        return False

    @staticmethod
    def _parse_size_gb(size: str) -> int:
        """Parse lsblk size string (e.g., '1.8T', '500G', '256M') to integer GB."""
        if "T" in size:
            return int(float(size.replace("T", "")) * TB_TO_GB_MULTIPLIER)
        if "G" in size:
            return int(float(size.replace("G", "")))
        if "M" in size:
            return max(1, int(float(size.replace("M", "")) / MB_PER_GB))
        if "P" in size:
            return int(float(size.replace("P", "")) * PB_TO_TB_MULTIPLIER * TB_TO_GB_MULTIPLIER)
        return 0

    @staticmethod
    def _get_hardware_ids(name: str) -> tuple[str | None, str | None, list[str]]:
        """Extract hardware identifiers (WWN, EUI, by-id links) for a device."""
        wwn = None
        eui = None
        by_id_links: list[str] = []
        logger = logging.getLogger(__name__)

        by_id_dir = Path("/dev/disk/by-id")
        try:
            if not by_id_dir.exists():
                return wwn, eui, by_id_links
            entries = [e.name for e in by_id_dir.iterdir()]
        except OSError:
            logger.debug("Cannot list %s", by_id_dir)
            return wwn, eui, by_id_links

        for link_name in entries:
            if "-part" in link_name:
                continue
            full_path = by_id_dir / link_name
            if not full_path.is_symlink():
                continue
            with contextlib.suppress(OSError):
                target = str(full_path.resolve())
                if target.endswith(name):
                    by_id_links.append(link_name)
                    if link_name.startswith("wwn-"):
                        wwn = link_name.replace("wwn-", "")
                    if link_name.startswith("nvme-eui."):
                        eui = link_name.replace("nvme-", "").split("_")[0]

        return wwn, eui, by_id_links

    @staticmethod
    def _detect_interface(name: str) -> str:
        """Determine the storage interface type for a device."""
        if "nvme" in name:
            nvme_info = run_command(["nvme", "id-ctrl", f"/dev/{name}"])
            return "PCIe NVMe" if nvme_info else "NVMe"

        sys_block_path = Path(f"/sys/block/{name}")
        if sys_block_path.exists():
            device_link_path = sys_block_path / "device"
            if device_link_path.exists():
                try:
                    device_real_path = str(device_link_path.resolve())
                    if "ata" in device_real_path:
                        return "SATA"
                except OSError:
                    pass

        return "Unknown"

    @staticmethod
    def _get_physical_block_size(name: str) -> int:
        """Get physical sector size for ashift calculation."""
        try:
            size_path = Path(f"/sys/block/{name}/queue/physical_block_size")
            if size_path.exists():
                return int(size_path.read_text().strip())
        except (OSError, ValueError):
            pass
        return DEFAULT_BLOCK_SIZE

    @staticmethod
    def _get_nvme_lba_formats(name: str) -> list[dict[str, Any]]:
        """Parse NVMe LBA format capabilities from nvme id-ns.

        Returns a list of LBA formats with data_size and relative_performance.
        Example: [{"id": 0, "data_size": 512, "rp": 0}, {"id": 1, "data_size": 4096, "rp": 1}]
        """
        output = run_command(["nvme", "id-ns", f"/dev/{name}"])
        if not output:
            return []

        formats: list[dict[str, Any]] = []
        for match in re.finditer(
            r"lbaf\s+(\d+)\s*:.*?ds:(\d+).*?rp:(0x[0-9a-fA-F]+|\d+)",
            output,
        ):
            lba_id = int(match.group(1))
            # ds field is log2(data_size), e.g. 9 = 512B, 12 = 4096B
            ds_exponent = int(match.group(2))
            data_size = 2**ds_exponent
            rp_str = match.group(3)
            rp = int(rp_str, 16) if rp_str.startswith("0x") else int(rp_str)
            formats.append({"id": lba_id, "data_size": data_size, "rp": rp})

        return formats

    @staticmethod
    def _get_recommended_block_size(name: str, disk_type: str) -> int:
        """Get recommended block size for ashift calculation.

        - NVMe: check LBA formats for 4096-byte support; default to 4096
        - SSD: default to 4096 (modern SSDs are all 4K+ internally)
        - HDD: trust sysfs physical_block_size
        """
        if disk_type == "NVMe":
            lba_formats = StorageDetector._get_nvme_lba_formats(name)
            if lba_formats:
                # If any LBA format supports 4096 or larger, recommend that
                max_lba_size = max(f["data_size"] for f in lba_formats)
                return max(4096, max_lba_size)
            # No parseable LBAF data — safe default for all modern NVMe
            return 4096

        if disk_type == "SSD":
            return 4096

        # HDD: trust the sysfs value
        return StorageDetector._get_physical_block_size(name)

    @staticmethod
    def _get_smart_data(name: str) -> dict[str, Any]:
        """Collect SMART data for a device (requires root)."""
        smart_data: dict[str, Any] = {}

        smart_health = run_command(["smartctl", "-H", f"/dev/{name}"])
        if smart_health:
            if "PASSED" in smart_health or "OK" in smart_health:
                smart_data["health_status"] = "PASSED"
            elif "FAILED" in smart_health:
                smart_data["health_status"] = "FAILED"

        smart_all = run_command(["smartctl", "-A", f"/dev/{name}"])
        if smart_all:
            temp_match = re.search(r"Temperature.*\s+(\d+)(?:\s+\(|$)", smart_all)
            if temp_match:
                smart_data["temperature_celsius"] = int(temp_match.group(1))

            hours_match = re.search(r"Power_On_Hours.*\s+(\d+)$", smart_all, re.MULTILINE)
            if hours_match:
                smart_data["power_on_hours"] = int(hours_match.group(1))

            wear_match = re.search(r"Wear_Leveling_Count.*\s+(\d+)$", smart_all, re.MULTILINE)
            if wear_match:
                smart_data["wear_leveling"] = int(wear_match.group(1))

            percent_used = re.search(r"Percentage Used.*\s+(\d+)%", smart_all)
            if percent_used:
                smart_data["percentage_used"] = int(percent_used.group(1))

        smart_info = run_command(["smartctl", "-i", f"/dev/{name}"])
        if smart_info:
            firmware_match = re.search(r"Firmware Version:\s+(.+)", smart_info)
            if firmware_match:
                smart_data["firmware_version"] = firmware_match.group(1).strip()

        return smart_data

    @staticmethod
    def detect() -> dict[str, Any]:
        """Detect storage devices and controllers."""
        storage_data: dict[str, Any] = {"devices": []}

        lsblk_output = run_command(["lsblk", "-d", "-o", "NAME,SIZE,TYPE,ROTA,MODEL", "-n"])

        for line in lsblk_output.split("\n"):
            if not line.strip():
                continue

            parts = line.split(maxsplit=4)
            if len(parts) < 4:
                continue

            name, size, dev_type, rota = parts[:4]
            model = parts[4].strip() if len(parts) > 4 else "Unknown"

            if dev_type != "disk":
                continue

            name = sanitize_device_name(name)
            if not name:
                continue

            if StorageDetector._is_usb_device(name):
                continue

            disk_type = "HDD" if rota == "1" else "SSD"
            if "nvme" in name:
                disk_type = "NVMe"

            wwn, eui, by_id_links = StorageDetector._get_hardware_ids(name)
            serial = run_command(["lsblk", "-no", "SERIAL", f"/dev/{name}"])

            device = {
                "name": name,
                "model": model,
                "model_id": model.replace(" ", "_"),
                "capacity_gb": StorageDetector._parse_size_gb(size),
                "type": disk_type,
                "interface": StorageDetector._detect_interface(name),
                "serial": serial if serial else f"SERIAL_PLACEHOLDER_{name}",
                "wwn": wwn,
                "eui": eui,
                "physical_block_size": StorageDetector._get_physical_block_size(name),
                "recommended_block_size": StorageDetector._get_recommended_block_size(name, disk_type),
                "by_id_links": by_id_links,
            }

            if is_root():
                smart_data = StorageDetector._get_smart_data(name)
                if smart_data:
                    device["smart"] = smart_data

            storage_data["devices"].append(device)

        return storage_data
