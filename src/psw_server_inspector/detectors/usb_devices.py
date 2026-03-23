"""USB serial device detection module.

Detects USB serial adapters (Zigbee dongles, Z-Wave sticks, etc.)
by scanning /dev/serial/by-id/ and enriching with lsusb data.
"""

import os
import re
from typing import Any

from psw_server_inspector.utils import run_command


class USBDeviceDetector:
    """Detect USB serial devices (dongles, adapters)."""

    # Known USB device types by vendor:product ID
    KNOWN_DEVICES: dict[str, str] = {
        # Zigbee adapters
        "1a86:55d4": "zigbee",   # SONOFF Zigbee 3.0 (CH9102)
        "1a86:7523": "zigbee",   # CH340 (common Zigbee adapter)
        "10c4:ea60": "zigbee",   # Silicon Labs CP2102 (Zigbee/generic)
        "10c4:8a2a": "zigbee",   # Silicon Labs (Zigbee coordinator)
        "1cf1:0030": "zigbee",   # ConBee II
        "0451:16a8": "zigbee",   # TI CC2531/CC2652 (Zigbee)
        # Z-Wave adapters
        "0658:0200": "zwave",    # Aeotec Z-Stick Gen5
        "0658:0280": "zwave",    # Aeotec Z-Stick Gen7
        "10c4:8856": "zwave",    # Silicon Labs (Z-Wave)
        "0403:6015": "zwave",    # FTDI (Zooz Z-Wave)
        # Generic serial adapters
        "0403:6001": "serial",   # FTDI FT232
        "067b:2303": "serial",   # Prolific PL2303
    }

    @staticmethod
    def detect() -> list[dict[str, Any]]:
        """Detect USB serial devices via /dev/serial/by-id/ and lsusb."""
        devices: list[dict[str, Any]] = []

        # Method 1: Scan /dev/serial/by-id/ for stable symlinks
        serial_by_id = "/dev/serial/by-id"
        if os.path.isdir(serial_by_id):
            for entry in sorted(os.listdir(serial_by_id)):
                full_path = os.path.join(serial_by_id, entry)
                if not os.path.islink(full_path):
                    continue

                real_dev = os.path.realpath(full_path)
                dev_info = _parse_serial_by_id_name(entry)
                dev_info["path"] = full_path
                dev_info["device"] = real_dev

                # Enrich with lsusb data if possible
                _enrich_with_lsusb(dev_info)

                # Classify device type
                vid_pid = f"{dev_info.get('vendor_id', '')}:{dev_info.get('product_id', '')}"
                dev_info["type"] = USBDeviceDetector.KNOWN_DEVICES.get(vid_pid, "unknown")

                devices.append(dev_info)

        # Method 2: Fallback — scan lsusb for known device types
        # (catches devices without /dev/serial/by-id/ entries)
        if not devices:
            lsusb_devices = _scan_lsusb_for_known_devices()
            devices.extend(lsusb_devices)

        return devices


def _parse_serial_by_id_name(name: str) -> dict[str, Any]:
    """Parse a /dev/serial/by-id/ symlink name into vendor/model/serial.

    Format: usb-<vendor>_<model>-<serial>-if<interface>
    Example: usb-ITEAD_SONOFF_Zigbee_3.0_USB_Dongle_Plus_V2_20231234567-if00-port0
    """
    info: dict[str, Any] = {"by_id_name": name}

    # Strip 'usb-' prefix and '-if*' suffix
    clean = name
    if clean.startswith("usb-"):
        clean = clean[4:]
    # Remove interface suffix
    clean = re.sub(r"-if\d+.*$", "", clean)

    # Split on last hyphen group for serial
    parts = clean.rsplit("-", 1)
    if len(parts) == 2:
        info["description"] = parts[0].replace("_", " ")
        info["serial"] = parts[1]
    else:
        info["description"] = clean.replace("_", " ")

    return info


def _enrich_with_lsusb(dev_info: dict[str, Any]) -> None:
    """Try to get vendor_id and product_id from lsusb for a device."""
    device = dev_info.get("device", "")
    if not device:
        return

    # Get bus and device number from the real device path
    # e.g., /dev/ttyUSB0 → find the USB parent in /sys
    dev_name = os.path.basename(device)

    # Try to read vendor/product from sysfs
    for base in [f"/sys/class/tty/{dev_name}/device", f"/sys/class/tty/{dev_name}/../.."]:
        vendor_path = os.path.join(base, "idVendor")
        product_path = os.path.join(base, "idProduct")
        if os.path.exists(vendor_path) and os.path.exists(product_path):
            try:
                with open(vendor_path) as f:
                    dev_info["vendor_id"] = f.read().strip()
                with open(product_path) as f:
                    dev_info["product_id"] = f.read().strip()
                return
            except OSError:
                continue

    # Fallback: try to extract from the by-id name using lsusb
    lsusb_output = run_command(["lsusb"])
    if not lsusb_output:
        return

    description = dev_info.get("description", "").lower()
    for line in lsusb_output.splitlines():
        # Format: Bus 001 Device 005: ID 1a86:55d4 QinHeng Electronics ...
        match = re.match(r"Bus \d+ Device \d+: ID ([0-9a-f]+):([0-9a-f]+)\s+(.*)", line)
        if match:
            vid, pid, desc = match.groups()
            if any(word in desc.lower() for word in description.split()[:3] if len(word) > 3):
                dev_info["vendor_id"] = vid
                dev_info["product_id"] = pid
                return


def _scan_lsusb_for_known_devices() -> list[dict[str, Any]]:
    """Scan lsusb output for known USB device types."""
    devices: list[dict[str, Any]] = []
    lsusb_output = run_command(["lsusb"])
    if not lsusb_output:
        return devices

    for line in lsusb_output.splitlines():
        match = re.match(r"Bus (\d+) Device (\d+): ID ([0-9a-f]+):([0-9a-f]+)\s+(.*)", line)
        if not match:
            continue
        bus, dev_num, vid, pid, desc = match.groups()
        vid_pid = f"{vid}:{pid}"
        if vid_pid in USBDeviceDetector.KNOWN_DEVICES:
            devices.append({
                "vendor_id": vid,
                "product_id": pid,
                "description": desc.strip(),
                "type": USBDeviceDetector.KNOWN_DEVICES[vid_pid],
                "bus": bus,
                "device_number": dev_num,
            })

    return devices
