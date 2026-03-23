"""Motherboard detection module"""

from typing import Any

from psw_server_inspector.utils import is_root, run_command


class MotherboardDetector:
    """Detect motherboard information"""

    @staticmethod
    def detect() -> dict[str, Any]:
        """Detect motherboard information."""
        mb_data = {}

        if is_root():
            manufacturer = run_command(["dmidecode", "-s", "baseboard-manufacturer"])
            product = run_command(["dmidecode", "-s", "baseboard-product-name"])
            version = run_command(["dmidecode", "-s", "baseboard-version"])
            serial = run_command(["dmidecode", "-s", "baseboard-serial-number"])

            if manufacturer and manufacturer not in ["", "To Be Filled By O.E.M."]:
                mb_data["manufacturer"] = manufacturer
            if product and product not in ["", "To Be Filled By O.E.M."]:
                mb_data["product_name"] = product
            if version and version not in ["", "To Be Filled By O.E.M."]:
                mb_data["version"] = version
            if serial and serial not in ["", "To Be Filled By O.E.M.", "Default string"]:
                mb_data["serial"] = serial

            bios_vendor = run_command(["dmidecode", "-s", "bios-vendor"])
            bios_version = run_command(["dmidecode", "-s", "bios-version"])
            bios_date = run_command(["dmidecode", "-s", "bios-release-date"])

            if bios_vendor:
                mb_data["bios_vendor"] = bios_vendor
            if bios_version:
                mb_data["bios_version"] = bios_version
            if bios_date:
                mb_data["bios_date"] = bios_date

            chassis_type = run_command(["dmidecode", "-s", "chassis-type"])
            if chassis_type and chassis_type != "Other":
                mb_data["chassis_type"] = chassis_type

        return mb_data
