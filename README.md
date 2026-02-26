> [!WARNING]
> This project is entirely vibecoded. Use at your own risk.

# server-inspector

Hardware detection and inventory tool for servers.

Detects CPU, memory, storage, network, GPU, USB controllers, motherboard, IPMI/BMC, and system capabilities — outputs a single YAML file for use by downstream tools.

## Quick Install

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/casaeureka/server-inspector/main/install-server-inspector.sh)"
```

The installer handles everything: Python 3.14, uv, system dependencies (pciutils, ethtool, dmidecode, smartmontools, nvme-cli, ipmitool), and the tool itself.

If curl isn't available (common on minimal installs):

```bash
wget -qO- https://raw.githubusercontent.com/casaeureka/server-inspector/main/install-server-inspector.sh | bash
```

Or via uv directly:

```bash
uv tool install server-inspector
```

## Usage

```bash
server-inspector white                          # inspect and write hardware-white.yml
server-inspector white --output /custom/path.yml # custom output path
server-inspector white --quiet                   # suppress non-error output
```

The first argument is the server name, used in the filename and YAML metadata. The `inspect` subcommand is implicit.

### Options

| Option | Description |
|--------|-------------|
| `name` | Server name (e.g., `white`, `pve01`) |
| `--output`, `-o` | Override output path (default: `hardware-<name>.yml`) |
| `--quiet` / `-q` | Suppress non-error output |
| `--verbose` / `-v` | Debug output |
| `--version` | Show version |

## Output

Produces `hardware-<name>.yml` with stable device paths (WWN/EUI-based `/dev/disk/by-id/` links). Example (abbreviated):

```yaml
collection_info:
  timestamp: "2026-01-15T10:30:00+00:00"
  inspector_version: "0.1.0"
  method: local
  server_name: white
server:
  model: "Custom Build"
  cpu:
    model: "Intel Xeon E-2388G"
    cores: 8
    threads: 16
    features: [Virtualization, Intel VT-d]
  memory:
    total_gb: 64
    type: DDR4
    ecc: true
disks:
  - interface: NVMe
    model: "Samsung SSD 980 PRO 1TB"
    device: "/dev/disk/by-id/nvme-eui.0025384..."
    capacity_gb: 953
network:
  interfaces:
    - interface: eno1
      mac: "aa:bb:cc:dd:ee:ff"
      speed: "1Gb/s"
motherboard:
  manufacturer: Supermicro
  product_name: "X12STH-F"
ipmi:
  device_present: true
  ip_address: "10.0.0.100"
# ... gpu, usb_controllers, system (boot_mode, tpm, etc.)
```

## Integration

Designed to feed into the [casaeureka](https://github.com/casaeureka) toolchain:

- **[proxmox-wizard](https://github.com/casaeureka/proxmox-wizard)** — imports via `hardware-detect` for automated Proxmox setup
- **[storage-planner](https://github.com/casaeureka/storage-planner)** — reads hardware.yml for AI storage planning
- **[disk-wiper](https://github.com/casaeureka/disk-wiper)** — wipe drives before Proxmox install

## Notes

- No `sudo` needed — the tool auto-escalates to root internally.
- Atomic writes — safe for USB drives.
- Some details (motherboard, IPMI) require root access.

---

Part of the [casaeureka](https://github.com/casaeureka) suite.

## License

MIT

## Support

[![GitHub Sponsors](https://img.shields.io/badge/GitHub-Sponsor-ea4aaa?logo=github)](https://github.com/sponsors/W3Max)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5f5f?logo=ko-fi)](https://ko-fi.com/w3max)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/w3max)
