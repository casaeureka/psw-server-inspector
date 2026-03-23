"""CPU detection module"""

import contextlib
import re
from typing import Any

from psw_server_inspector.utils import PSUTIL_AVAILABLE, run_command

if PSUTIL_AVAILABLE:
    import psutil


class CPUDetector:
    """Detect CPU information"""

    @staticmethod
    def _detect_iommu_support(cpu_manufacturer: str) -> dict[str, Any]:
        """Detect IOMMU hardware support and kernel status.

        Args:
            cpu_manufacturer: CPU manufacturer ("AMD" or "Intel")

        Returns:
            Dictionary with 'supported', 'enabled', and 'type' keys
        """
        # Check dmesg for IOMMU hardware presence
        # DMAR = DMA Remapping (Intel VT-d), AMD-Vi = AMD I/O Virtualization
        dmesg_output = run_command(["dmesg"], timeout=5)
        has_dmar = "DMAR:" in dmesg_output
        has_amd_vi = "AMD-Vi:" in dmesg_output

        iommu_intel_enabled = "DMAR: IOMMU enabled" in dmesg_output
        iommu_amd_enabled = "AMD-Vi: Found IOMMU" in dmesg_output

        cmdline = run_command(["cat", "/proc/cmdline"])
        iommu_cmdline = "intel_iommu=on" in cmdline or "amd_iommu=on" in cmdline

        if "AMD" in cpu_manufacturer:
            return {
                "type": "AMD-Vi",
                "supported": has_amd_vi,
                "enabled": bool(iommu_amd_enabled or iommu_cmdline),
            }
        if "Intel" in cpu_manufacturer:
            return {
                "type": "Intel VT-d",
                "supported": has_dmar,
                "enabled": bool(iommu_intel_enabled or iommu_cmdline),
            }
        return {
            "type": "None",
            "supported": False,
            "enabled": False,
        }

    @staticmethod
    def _parse_lscpu() -> dict[str, str]:
        """Parse lscpu output into a field dictionary."""
        lscpu_output = run_command(["lscpu"])
        fields: dict[str, str] = {
            "model": "",
            "architecture": "",
            "vendor": "",
            "threads": "",
            "cores_per_socket": "",
            "sockets": "",
            "max_mhz": "",
            "virtualization": "",
        }
        key_map = {
            "Model name:": "model",
            "Architecture:": "architecture",
            "Vendor ID:": "vendor",
            "CPU(s):": "threads",
            "Core(s) per socket:": "cores_per_socket",
            "Socket(s):": "sockets",
            "CPU max MHz:": "max_mhz",
        }
        for line in lscpu_output.split("\n"):
            for prefix, key in key_map.items():
                if line.startswith(prefix):
                    fields[key] = line.split(":", 1)[1].strip()
                    break
            else:
                if "Virtualization:" in line or "VT-x" in line or "AMD-V" in line:
                    fields["virtualization"] = line.split(":", 1)[1].strip() if ":" in line else line.strip()
        return fields

    @staticmethod
    def _clean_model_name(raw_model: str) -> tuple[str, str | None]:
        """Clean CPU model name and extract base clock if present.

        Returns:
            Tuple of (cleaned model name, base clock string or None)
        """
        base_clock = None
        if raw_model:
            match = re.search(r"@\s*([\d.]+)\s*GHz", raw_model)
            if match:
                base_clock = f"{match.group(1)} GHz"

        model = raw_model
        if model:
            model = re.sub(r"\s+Unknown CPU @ [\d.]+GHz", "", model).strip()
            # Deduplicate model string (e.g., "AMD Ryzen 9 ... AMD Ryzen 9 ...")
            words = model.split()
            if len(words) >= 4 and len(words) % 2 == 0:
                half = len(words) // 2
                if " ".join(words[:half]) == " ".join(words[half:]):
                    model = " ".join(words[:half])

        return model, base_clock

    @staticmethod
    def detect() -> dict[str, Any]:
        """Detect CPU information."""
        lscpu = CPUDetector._parse_lscpu()
        model, base_clock = CPUDetector._clean_model_name(lscpu["model"])

        cpu_data: dict[str, Any] = {
            "model": model,
            "architecture": lscpu["architecture"],
            "manufacturer": "AMD" if "AMD" in lscpu["vendor"] or "AuthenticAMD" in lscpu["vendor"] else "Intel",
        }

        if PSUTIL_AVAILABLE:
            cpu_data["cores"] = psutil.cpu_count(logical=False)
            cpu_data["threads"] = psutil.cpu_count(logical=True)
        else:
            cpu_data["threads"] = int(lscpu["threads"]) if lscpu["threads"].isdigit() else 0
            if lscpu["cores_per_socket"].isdigit() and lscpu["sockets"].isdigit():
                cpu_data["cores"] = int(lscpu["cores_per_socket"]) * int(lscpu["sockets"])

        if lscpu["max_mhz"]:
            with contextlib.suppress(ValueError):
                cpu_data["boost_clock"] = f"{float(lscpu['max_mhz']) / 1000:.1f} GHz"
        if base_clock:
            cpu_data["base_clock"] = base_clock

        virt = lscpu["virtualization"]
        cpu_data["virtualization_supported"] = bool(virt)
        cpu_data["virtualization_type"] = virt if virt else "None"

        iommu_info = CPUDetector._detect_iommu_support(cpu_data["manufacturer"])
        cpu_data["iommu"] = iommu_info

        cpu_data["features"] = []
        if cpu_data["virtualization_supported"]:
            cpu_data["features"].append("Virtualization")
        if iommu_info["supported"]:
            cpu_data["features"].append(iommu_info["type"])

        return cpu_data
