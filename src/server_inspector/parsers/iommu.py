"""IOMMU group detection utilities"""

from pathlib import Path


def get_iommu_group(pci_address: str) -> int | None:
    """Get IOMMU group number for PCI device.

    Args:
        pci_address: PCI address in format "0000:00:00.0"

    Returns:
        IOMMU group number or None if not found/not enabled
    """
    iommu_path = Path(f"/sys/bus/pci/devices/{pci_address}/iommu_group")

    if not iommu_path.exists() or not iommu_path.is_symlink():
        return None

    try:
        resolved = str(iommu_path.resolve())
        group_name = resolved.rsplit("/", 1)[-1]

        if group_name.isdigit():
            return int(group_name)
    except (OSError, ValueError):
        pass

    return None
