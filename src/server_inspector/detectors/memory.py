"""Memory detection module"""

import math
import re
from typing import Any

from server_inspector.utils import (
    BYTES_PER_GB,
    COMMON_RAM_SIZES_GB,
    KB_PER_GB,
    PSUTIL_AVAILABLE,
    RAM_SIZE_TOLERANCE_GB,
    is_root,
    print_warning,
    run_command,
)

if PSUTIL_AVAILABLE:
    import psutil


class MemoryDetector:
    """Detect memory information"""

    @staticmethod
    def _round_to_common_size(mem_gb_raw: float) -> int:
        """Round raw GB value to nearest common RAM size (e.g., 62 -> 64, 31 -> 32)."""
        for size in COMMON_RAM_SIZES_GB:
            if abs(mem_gb_raw - size) <= RAM_SIZE_TOLERANCE_GB:
                return size
        return int(math.ceil(mem_gb_raw))

    @staticmethod
    def detect() -> dict[str, Any]:
        """Detect memory information."""
        mem_data = {}

        if PSUTIL_AVAILABLE:
            mem = psutil.virtual_memory()
            mem_data["total_gb"] = MemoryDetector._round_to_common_size(mem.total / BYTES_PER_GB)
        else:
            meminfo = run_command(["cat", "/proc/meminfo"])
            total_kb = ""
            for line in meminfo.split("\n"):
                if line.startswith("MemTotal:"):
                    total_kb = line.split()[1]
                    break
            if total_kb.isdigit():
                mem_data["total_gb"] = MemoryDetector._round_to_common_size(int(total_kb) / KB_PER_GB)

        if is_root():
            modules = []
            dmidecode_out = run_command(["dmidecode", "-t", "memory"])

            current_module: dict[str, Any] = {}
            for line in dmidecode_out.split("\n"):
                line = line.strip()

                if line.startswith("Memory Device"):
                    if current_module and current_module.get("size"):
                        modules.append(current_module)
                    current_module = {}
                elif ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower().replace(" ", "_")
                    value = value.strip()

                    if key == "size" and value not in ["No Module Installed", "Not Installed"]:
                        current_module["size"] = value
                    elif key == "type" and value != "Unknown":
                        current_module["type"] = value
                    elif key == "speed" and value != "Unknown":
                        current_module["speed"] = value
                    elif key == "manufacturer" and value not in ["NO DIMM", "Unknown"]:
                        current_module["manufacturer"] = value
                    elif key == "locator":
                        current_module["slot"] = value

            if current_module and current_module.get("size"):
                modules.append(current_module)

            mem_data["slots_used"] = len(modules)

            total_slots = dmidecode_out.count("Memory Device")
            if total_slots > 0:
                mem_data["slots_total"] = total_slots

            if modules:
                mem_data["type"] = modules[0].get("type", "Unknown")
                mem_data["speed"] = modules[0].get("speed", "Unknown")

            ecc_type = None
            for line in dmidecode_out.split("\n"):
                if "Error Correction Type:" in line:
                    ecc_type = line.split(":", 1)[1].strip()
                    break
            if ecc_type is None:
                mem_data["ecc"] = False
            else:
                mem_data["ecc"] = ecc_type not in ("None", "Unknown", "")

            if mem_data.get("slots_total") and mem_data.get("slots_used"):
                empty_slots = mem_data["slots_total"] - mem_data["slots_used"]
                if empty_slots > 0 and mem_data.get("total_gb") and modules:
                    # Calculate per-module size from actual module (e.g., "32 GB")
                    first_module_size = modules[0].get("size", "")
                    size_match = re.search(r"(\d+)\s*GB", first_module_size)
                    if size_match:
                        per_module_gb = float(size_match.group(1))
                        max_possible = per_module_gb * mem_data["slots_total"]
                        mem_data["expandable_to_gb"] = int(max_possible)
                    else:
                        # Fallback: use current total divided by slots
                        per_module_gb = float(mem_data["total_gb"]) / mem_data["slots_used"]
                        max_possible = per_module_gb * mem_data["slots_total"]
                        mem_data["expandable_to_gb"] = int(max_possible)
        else:
            print_warning("Not running as root - limited memory details available")

        return mem_data
