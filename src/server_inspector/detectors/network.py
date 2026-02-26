"""Network interface detection module."""

import contextlib
import re
import socket
from pathlib import Path
from typing import Any

from server_inspector.parsers.iommu import get_iommu_group
from server_inspector.parsers.pci import extract_pci_address_from_path, parse_pci_ids, parse_subsystem_id
from server_inspector.utils import MBPS_TO_GBPS_DIVISOR, PSUTIL_AVAILABLE, run_command, sanitize_device_name

from .network_pcie import detect_current_network, detect_pcie_cards

if PSUTIL_AVAILABLE:
    import psutil


class NetworkDetector:
    """Detect network interfaces, PCIe cards, and current network config."""

    @staticmethod
    def _detect_interface_speed(iface_name: str, stats: dict | None = None) -> int:
        """Detect maximum interface speed in Mbps."""
        speed_mbps = 0

        ethtool_full = run_command(["ethtool", iface_name])
        if ethtool_full:
            speeds = re.findall(r"(\d+)base", ethtool_full)
            if speeds:
                speed_mbps = max(int(s) for s in speeds)

        if speed_mbps == 0 and stats and iface_name in stats:
            stat = stats[iface_name]
            speed_mbps = stat.speed if stat.speed > 0 else 0

        return speed_mbps

    @staticmethod
    def _format_speed(speed_mbps: int) -> str:
        """Format speed in Mbps to human-readable string."""
        if speed_mbps >= MBPS_TO_GBPS_DIVISOR:
            return f"{speed_mbps / MBPS_TO_GBPS_DIVISOR}Gb/s"
        if speed_mbps > 0:
            return f"{speed_mbps}Mb/s"
        return "Unknown"

    @staticmethod
    def _get_pci_info(pci_addr: str, iface_data: dict) -> None:
        """Get PCI hardware information for interface and update iface_data in place."""
        iface_data["pci_address"] = pci_addr

        pci_short = pci_addr.split(":", 1)[1]
        lspci_line = run_command(["lspci", "-nn", "-s", pci_short])
        if lspci_line:
            pci_ids = parse_pci_ids(lspci_line)
            if pci_ids:
                vendor_id, device_id = pci_ids
                iface_data["pci_ids"] = {
                    "vendor": vendor_id,
                    "device": device_id,
                    "full": f"{vendor_id}:{device_id}",
                }

            lspci_verbose = run_command(["lspci", "-vnn", "-s", pci_short])
            subsystem_id = parse_subsystem_id(lspci_verbose)
            if subsystem_id:
                iface_data["subsystem_id"] = subsystem_id

        iommu_group = get_iommu_group(pci_addr)
        if iommu_group is not None:
            iface_data["iommu_group"] = iommu_group

        if lspci_line:
            desc_match = re.search(r":\s+(.+?)\s+\[", lspci_line)
            if desc_match:
                iface_data["device_name"] = desc_match.group(1).strip()

    @staticmethod
    def _enrich_with_sysfs(iface_name: str, iface_data: dict[str, Any]) -> None:
        """Enrich interface data with sysfs information (driver, PCI address)."""
        driver_path = Path(f"/sys/class/net/{iface_name}/device/driver")
        if driver_path.exists() and driver_path.is_symlink():
            with contextlib.suppress(OSError):
                resolved = str(driver_path.resolve())
                driver = resolved.rsplit("/", 1)[-1]
                if driver:
                    iface_data["driver"] = driver

        device_path_link = Path(f"/sys/class/net/{iface_name}/device")
        if device_path_link.exists() and device_path_link.is_symlink():
            with contextlib.suppress(OSError):
                readlink_output = run_command(["readlink", str(device_path_link)])
                if readlink_output:
                    pci_addr = extract_pci_address_from_path(readlink_output)
                    if pci_addr:
                        NetworkDetector._get_pci_info(pci_addr, iface_data)

    @staticmethod
    def _detect_interface_with_psutil(iface_name: str, iface_addrs: list, stats: dict) -> dict[str, Any]:
        """Detect single network interface using psutil."""
        iface_data: dict[str, Any] = {"interface": iface_name, "type": "Ethernet"}

        for addr in iface_addrs:
            if addr.family == socket.AF_INET:
                iface_data["ipv4"] = addr.address
                iface_data["netmask"] = addr.netmask
            elif addr.family == socket.AF_PACKET:
                iface_data["mac"] = addr.address

        speed_mbps = NetworkDetector._detect_interface_speed(iface_name, stats)
        iface_data["speed"] = NetworkDetector._format_speed(speed_mbps)

        if iface_name in stats:
            stat = stats[iface_name]
            iface_data["is_up"] = stat.isup

        NetworkDetector._enrich_with_sysfs(iface_name, iface_data)
        return iface_data

    @staticmethod
    def _detect_interfaces_psutil() -> list[dict[str, Any]]:
        """Detect all network interfaces using psutil."""
        interfaces = []
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()

        for iface_name, iface_addrs in addrs.items():
            if iface_name == "lo":
                continue

            iface_name = sanitize_device_name(iface_name)
            if not iface_name:
                continue

            iface_data = NetworkDetector._detect_interface_with_psutil(iface_name, iface_addrs, stats)
            interfaces.append(iface_data)

        return interfaces

    @staticmethod
    def _detect_interfaces_fallback() -> list[dict[str, Any]]:
        """Detect network interfaces without psutil (fallback method)."""
        interfaces = []
        ip_output = run_command(["ip", "-br", "addr", "show"])
        for line in ip_output.split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            iface_name = parts[0]
            if iface_name == "lo":
                continue
            iface_data: dict[str, Any] = {"interface": iface_name, "type": "Ethernet"}
            if len(parts) >= 3:
                iface_data["ipv4"] = parts[2].split("/")[0]

            # Enrich with sysfs even in fallback mode
            NetworkDetector._enrich_with_sysfs(iface_name, iface_data)
            interfaces.append(iface_data)
        return interfaces

    @staticmethod
    def detect() -> dict[str, Any]:
        """Detect network interfaces, PCIe cards, and current network configuration."""
        if PSUTIL_AVAILABLE:
            interfaces = NetworkDetector._detect_interfaces_psutil()
        else:
            interfaces = NetworkDetector._detect_interfaces_fallback()

        return {
            "interfaces": interfaces,
            "pcie_cards": detect_pcie_cards(),
            "current_network": detect_current_network(),
        }
