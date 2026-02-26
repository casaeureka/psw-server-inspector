"""IPMI/BMC detection module"""

import re
from pathlib import Path
from typing import Any

from server_inspector.utils import is_root, run_command


class IPMIDetector:
    """Detect IPMI/BMC management interface"""

    @staticmethod
    def detect() -> dict[str, Any]:
        """Detect IPMI/BMC information."""
        ipmi_data: dict[str, Any] = {}

        try:
            ipmi_devs = list(Path("/dev").glob("ipmi*"))
            ipmi_dev = len(ipmi_devs) > 0
        except OSError:
            ipmi_dev = False
        if not ipmi_dev:
            return ipmi_data

        ipmi_data["device_present"] = True

        if is_root():
            bmc_info = run_command(["ipmitool", "bmc", "info"])
            if bmc_info:
                manufacturer_match = re.search(r"Manufacturer Name\s*:\s*(.+)", bmc_info)
                if manufacturer_match:
                    ipmi_data["manufacturer"] = manufacturer_match.group(1).strip()

                product_match = re.search(r"Product Name\s*:\s*(.+)", bmc_info)
                if product_match:
                    ipmi_data["product_name"] = product_match.group(1).strip()

                firmware_match = re.search(r"Firmware Revision\s*:\s*(.+)", bmc_info)
                if firmware_match:
                    ipmi_data["firmware_version"] = firmware_match.group(1).strip()

            lan_print = run_command(["ipmitool", "lan", "print"])
            if lan_print:
                ip_match = re.search(r"IP Address\s*:\s*(\d+\.\d+\.\d+\.\d+)", lan_print)
                if ip_match:
                    ip_addr = ip_match.group(1)
                    if ip_addr != "0.0.0.0":  # nosec B104
                        ipmi_data["ip_address"] = ip_addr

                mac_match = re.search(r"MAC Address\s*:\s*([0-9a-f:]+)", lan_print, re.IGNORECASE)
                if mac_match:
                    ipmi_data["mac_address"] = mac_match.group(1).lower()

        return ipmi_data
