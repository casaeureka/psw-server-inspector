"""GPU detection module"""

import re
from typing import Any

from psw_server_inspector.parsers.iommu import get_iommu_group
from psw_server_inspector.utils import run_command


class GPUDetector:
    """Detect GPU devices"""

    @staticmethod
    def detect() -> list[dict[str, Any]]:
        """Detect GPU devices."""
        gpus = []

        lspci_output = run_command(["lspci", "-nn"])
        vga_lines = [
            line for line in lspci_output.split("\n") if any(kw in line.lower() for kw in ("vga", "3d", "display"))
        ]

        for line in vga_lines:
            match = re.match(r"([0-9a-f:\.]+)\s+.*?:\s+(.+)\s+\[([0-9a-f]+):([0-9a-f]+)\]", line)
            if match:
                pci_addr, description, vendor_id, device_id = match.groups()

                gpu: dict[str, Any] = {
                    "name": description.strip(),
                    "pci_address": f"0000:{pci_addr}",
                    "pci_ids": {"gpu": f"{vendor_id}:{device_id}"},
                }

                desc_lower = description.lower()
                if "nvidia" in desc_lower:
                    gpu["manufacturer"] = "NVIDIA"
                elif "amd" in desc_lower or "radeon" in desc_lower:
                    gpu["manufacturer"] = "AMD"
                elif "intel" in desc_lower:
                    gpu["manufacturer"] = "Intel"
                    gpu["type"] = "Integrated"

                full_pci_addr = f"0000:{pci_addr}"
                iommu_group = get_iommu_group(full_pci_addr)
                if iommu_group is not None:
                    gpu["iommu_group"] = iommu_group

                # Find associated audio device (GPU audio - usually in same IOMMU group)
                # Audio device is typically at function .1 of the same device
                base_addr = pci_addr.rsplit(".", 1)[0]
                audio_search = ""
                for audio_line in lspci_output.split("\n"):
                    if base_addr in audio_line and "audio" in audio_line.lower():
                        audio_search = audio_line
                        break
                if audio_search:
                    audio_match = re.search(r"\[([0-9a-f]+):([0-9a-f]+)\]", audio_search)
                    if audio_match:
                        audio_vendor, audio_device = audio_match.groups()
                        gpu["pci_ids"]["audio"] = f"{audio_vendor}:{audio_device}"

                if gpu.get("type") != "Integrated":
                    gpu["primary_usage"] = "Media transcoding (Plex/Jellyfin) or GPU passthrough"

                gpus.append(gpu)

        return gpus
