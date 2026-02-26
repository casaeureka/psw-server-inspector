"""PCIe network card detection module."""

import contextlib
import re
from pathlib import Path
from typing import Any

from server_inspector.parsers.iommu import get_iommu_group
from server_inspector.parsers.pci import extract_pci_address_from_path, parse_subsystem_id
from server_inspector.utils import run_command


def get_pci_to_interface_map() -> dict[str, list[str]]:
    """Build a map of PCI addresses to Linux interface names."""
    pci_to_iface: dict[str, list[str]] = {}

    net_path = Path("/sys/class/net")
    if not net_path.exists():
        return pci_to_iface

    for iface_dir in net_path.iterdir():
        iface_name = iface_dir.name
        if iface_name == "lo":
            continue

        device_link = iface_dir / "device"
        if device_link.exists() and device_link.is_symlink():
            try:
                readlink_output = run_command(["readlink", str(device_link)])
                if readlink_output:
                    pci_addr = extract_pci_address_from_path(readlink_output)
                    if pci_addr:
                        if pci_addr not in pci_to_iface:
                            pci_to_iface[pci_addr] = []
                        pci_to_iface[pci_addr].append(iface_name)
            except (OSError, RuntimeError):
                pass

    return pci_to_iface


def detect_pcie_cards() -> list[dict[str, Any]]:
    """Detect PCIe network cards with their Linux interface names."""
    pcie_cards = []
    lspci_output = run_command(["lspci", "-nn"])

    pci_to_iface = get_pci_to_interface_map()

    nic_lines = [line for line in lspci_output.split("\n") if "network" in line.lower() or "ethernet" in line.lower()]

    for line in nic_lines:
        match = re.match(r"([0-9a-f:\.]+)\s+.*?:\s+(.+)\s+\[([0-9a-f]+):([0-9a-f]+)\]", line)
        if match:
            pci_addr, description, vendor_id, device_id = match.groups()
            full_pci_addr = f"0000:{pci_addr}"

            card: dict[str, Any] = {
                "name": description.strip(),
                "pci_address": full_pci_addr,
                "vendor_id": vendor_id,
                "device_id": device_id,
                "type": "10Gb Ethernet" if "10" in description else "Ethernet",
            }

            interfaces = pci_to_iface.get(full_pci_addr, [])
            if interfaces:
                if len(interfaces) == 1:
                    card["interface"] = interfaces[0]
                else:
                    card["interfaces"] = sorted(interfaces)
                first_iface = interfaces[0]
                driver_path = Path(f"/sys/class/net/{first_iface}/device/driver")
                if driver_path.exists() and driver_path.is_symlink():
                    with contextlib.suppress(OSError):
                        card["driver"] = str(driver_path.resolve()).rsplit("/", 1)[-1]

            lspci_verbose = run_command(["lspci", "-vnn", "-s", pci_addr])
            subsystem_id = parse_subsystem_id(lspci_verbose)
            if subsystem_id:
                card["subsystem_id"] = subsystem_id

            iommu_group = get_iommu_group(full_pci_addr)
            if iommu_group is not None:
                card["iommu_group"] = iommu_group

            pcie_cards.append(card)

    return pcie_cards


def detect_current_network() -> dict[str, Any]:
    """Detect current network configuration (gateway, DNS)."""
    current_network: dict[str, Any] = {}

    ip_route_output = run_command(["ip", "route", "show", "default"])
    default_route = ip_route_output.split("\n")[0] if ip_route_output else ""
    if default_route:
        parts = default_route.split()
        if "via" in parts:
            gateway_idx = parts.index("via") + 1
            if gateway_idx < len(parts):
                current_network["gateway"] = parts[gateway_idx]
        if "dev" in parts:
            dev_idx = parts.index("dev") + 1
            if dev_idx < len(parts):
                current_network["interface"] = parts[dev_idx]

    resolv_conf = run_command(["cat", "/etc/resolv.conf"])
    dns_servers_list = []
    for line in resolv_conf.split("\n"):
        if line.strip().startswith("nameserver"):
            parts = line.split()
            if len(parts) >= 2:
                dns_servers_list.append(parts[1])
    if dns_servers_list:
        current_network["dns_servers"] = dns_servers_list

    return current_network
