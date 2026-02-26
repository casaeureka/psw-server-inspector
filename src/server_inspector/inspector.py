"""Server hardware inspector - detection orchestration and YAML output."""

import contextlib
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import yaml

from . import __version__
from .detectors.cpu import CPUDetector
from .detectors.gpu import GPUDetector
from .detectors.ipmi import IPMIDetector
from .detectors.memory import MemoryDetector
from .detectors.motherboard import MotherboardDetector
from .detectors.network import NetworkDetector
from .detectors.storage import StorageDetector
from .detectors.system import SystemDetector
from .detectors.usb import USBControllerDetector
from .utils import PSUTIL_AVAILABLE, print_error, print_header, print_status, print_success, print_warning

VERSION: str = __version__

_CPU_FIELDS = ("manufacturer", "model", "cores", "threads", "architecture", "features", "base_clock", "boost_clock")
_MEMORY_FIELDS = ("total_gb", "type", "speed", "ecc", "slots_used", "slots_total", "expandable_to_gb")


class ServerInspector:
    """Main inspector — detects hardware and outputs standardized YAML."""

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.specs: dict[str, Any] = {
            "collection_info": {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "inspector_version": VERSION,
                "method": "local",
                "server_name": server_name,
            },
            "server": {},
            "storage": {},
            "network": {},
            "gpu": [],
            "usb_controllers": [],
            "motherboard": {},
            "ipmi": {},
            "system": {},
        }

    @staticmethod
    def _detect_and_report(
        label: str,
        detector_fn: Callable[[], Any],
        success_fmt: Callable[[Any], str],
        fallback: tuple[Callable[[Any], bool], str] | None = None,
    ) -> Any:
        """Run a detector, print progress and result.

        Args:
            label: Human-readable name for the detection step
            detector_fn: Callable that returns detection results
            success_fmt: Callable(result) -> success message string
            fallback: Optional (predicate, message) tuple; shows message when predicate returns False
        """
        print_status("\U0001f50d", f"Detecting {label}...")
        result = detector_fn()

        if fallback is not None:
            predicate, msg = fallback
            if not predicate(result):
                print_status("\u2139\ufe0f", msg)
                return result

        print_success(success_fmt(result))
        return result

    def run(self) -> dict[str, Any]:
        """Run all detection modules."""
        print_header(f"SERVER HARDWARE INSPECTOR - {self.server_name}")

        if not PSUTIL_AVAILABLE:
            print_warning("Missing optional dependency: psutil")
            print_status("", "  Some features may be limited.")
            print_status("", "  Run: uv tool install server-inspector (or uv sync for development)")

        self.specs["server"]["cpu"] = self._detect_and_report("CPU", CPUDetector.detect, lambda r: f"CPU: {r['model']}")
        self.specs["server"]["memory"] = self._detect_and_report(
            "Memory", MemoryDetector.detect, lambda r: f"Memory: {r.get('total_gb', '?')} GB"
        )
        self.specs["storage"] = self._detect_and_report(
            "Storage", StorageDetector.detect, lambda r: f"Storage: {len(r['devices'])} device(s) found"
        )
        self.specs["network"] = self._detect_and_report(
            "Network", NetworkDetector.detect, lambda r: f"Network: {len(r['interfaces'])} interface(s) found"
        )
        self.specs["gpu"] = self._detect_and_report(
            "GPU",
            GPUDetector.detect,
            lambda r: f"GPU: {len(r)} device(s) found",
            fallback=(bool, "No discrete GPU detected"),
        )
        self.specs["usb_controllers"] = self._detect_and_report(
            "USB Controllers",
            USBControllerDetector.detect,
            lambda r: f"USB: {len(r)} controller(s) found",
        )
        self.specs["motherboard"] = self._detect_and_report(
            "Motherboard",
            MotherboardDetector.detect,
            lambda r: f"Motherboard: {r['product_name']}",
            fallback=(lambda r: r.get("product_name"), "Motherboard info limited (not running as root)"),
        )
        self.specs["ipmi"] = self._detect_and_report(
            "IPMI/BMC",
            IPMIDetector.detect,
            lambda r: f"IPMI: Detected ({r.get('manufacturer', 'Unknown')})",
            fallback=(lambda r: r.get("device_present"), "No IPMI/BMC detected"),
        )
        self.specs["system"] = self._detect_and_report(
            "System Info", SystemDetector.detect, lambda r: f"System: {r['boot_mode']}"
        )

        return self.specs

    @staticmethod
    def _resolve_stable_device_path(by_id_links: list[str]) -> str | None:
        """Resolve the most stable device path from by-id symlinks.

        Priority: WWN > EUI (NVMe) > first available by-id link.
        """
        wwn_links = [link for link in by_id_links if link.startswith("wwn-")]
        eui_links = [link for link in by_id_links if link.startswith("nvme-eui.")]

        if wwn_links:
            return f"/dev/disk/by-id/{wwn_links[0]}"
        if eui_links:
            return f"/dev/disk/by-id/{eui_links[0]}"
        if by_id_links:
            return f"/dev/disk/by-id/{by_id_links[0]}"
        return None

    @staticmethod
    def _transform_disk(dev: dict[str, Any]) -> dict[str, Any]:
        """Transform a raw storage device into the hardware.yml disk schema."""
        by_id_links = dev.get("by_id_links", [])
        device_path = ServerInspector._resolve_stable_device_path(by_id_links)

        disk: dict[str, Any] = {"interface": dev.get("interface", "Unknown")}
        if device_path:
            disk["device"] = device_path
        for field in ("name", "model", "model_id", "serial", "capacity_gb", "type"):
            if dev.get(field) is not None:
                disk[field] = dev[field]
        if by_id_links:
            disk["by_id_links"] = by_id_links
        if dev.get("wwn"):
            disk["wwn"] = dev["wwn"]
        if dev.get("eui"):
            disk["eui"] = dev["eui"]
        if dev.get("physical_block_size") is not None:
            disk["physical_block_size"] = dev["physical_block_size"]

        return disk

    def build_hardware_dict(self) -> dict[str, Any]:
        """Build the standardized hardware.yml dictionary from raw specs."""
        hw: dict[str, Any] = {}

        if self.specs.get("collection_info"):
            hw["collection_info"] = self.specs["collection_info"]

        cpu_data = self.specs.get("server", {}).get("cpu", {})
        mem_data = self.specs.get("server", {}).get("memory", {})
        mb_data = self.specs.get("motherboard", {})

        hw["server"] = {
            "model": mb_data.get("product_name") or "Custom Build",
            "cpu": {k: v for k in _CPU_FIELDS if (v := cpu_data.get(k)) is not None},
            "memory": {k: v for k in _MEMORY_FIELDS if (v := mem_data.get(k)) is not None},
        }

        devices = self.specs.get("storage", {}).get("devices", [])
        hw["disks"] = [self._transform_disk(dev) for dev in devices]

        net_data = self.specs.get("network", {})
        hw["network"] = {}
        if net_data.get("interfaces"):
            hw["network"]["interfaces"] = net_data["interfaces"]
        if net_data.get("pcie_cards"):
            hw["network"]["pcie_cards"] = net_data["pcie_cards"]

        hw["gpu"] = self.specs.get("gpu", [])

        if self.specs.get("usb_controllers"):
            hw["usb_controllers"] = self.specs["usb_controllers"]
        if self.specs.get("motherboard"):
            hw["motherboard"] = self.specs["motherboard"]
        if self.specs.get("ipmi"):
            hw["ipmi"] = self.specs["ipmi"]
        if self.specs.get("system"):
            hw["system"] = self.specs["system"]

        return hw

    def save_yaml(self, output_file: str) -> None:
        """Save specs as universal hardware.yml for consumption by other tools.

        Transforms the raw detection data into a standardized schema that
        storage-planner, proxmox-wizard, and other tools can consume directly.
        """
        hw = self.build_hardware_dict()

        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(output_file) or ".", prefix=".tmp_hw_")
        success = False
        try:
            with os.fdopen(temp_fd, "w") as f:
                yaml.dump(hw, f, default_flow_style=False, sort_keys=False)
            os.replace(temp_path, output_file)
            os.sync()
            success = True
            print_success(f"Saved to: {output_file}")
        finally:
            if not success:
                with contextlib.suppress(OSError):
                    os.unlink(temp_path)

    def print_summary(self) -> None:
        """Print summary of detected hardware."""
        print_header("DETECTION SUMMARY")

        cpu = self.specs["server"]["cpu"]
        mem = self.specs["server"]["memory"]

        ram_detail = f"{mem.get('total_gb', '?')} GB"
        if mem.get("type"):
            ram_detail += f" ({mem.get('type')} @ {mem.get('speed', 'Unknown')})"

        print_status("", f"  CPU: {cpu.get('model', 'Unknown')}")
        print_status("", f"  Cores: {cpu.get('cores', '?')} physical / {cpu.get('threads', '?')} logical")
        print_status("", f"  RAM: {ram_detail}")
        print_status("", f"  Storage: {len(self.specs['storage']['devices'])} device(s)")
        print_status("", f"  Network: {len(self.specs['network']['interfaces'])} interface(s)")
        print_status("", f"  GPU: {len(self.specs['gpu'])} device(s)")

        virt_supported = cpu.get("virtualization_supported", False)
        if virt_supported:
            print_success("Ready for Proxmox VE (virtualization supported)")
        else:
            print_error("Virtualization not supported - cannot run Proxmox VE")
