"""Utility functions for server inspector."""

import importlib.util
import logging
import os
import re
import subprocess
import sys
from typing import NoReturn

from server_inspector.colors import Colors

logger = logging.getLogger(__name__)

# Dependency availability (checked once at import time)
PSUTIL_AVAILABLE = importlib.util.find_spec("psutil") is not None

# Command and UI Constants
COMMAND_TIMEOUT_SECONDS = 10  # Default subprocess timeout
HEADER_WIDTH = 70  # Width of header lines
COMMON_RAM_SIZES_GB = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]  # Common RAM module sizes
RAM_SIZE_TOLERANCE_GB = 3  # Tolerance for matching common RAM sizes
KB_PER_GB = 1024 * 1024  # Kilobytes per gigabyte (1,048,576)
BYTES_PER_GB = 1024**3  # Bytes per gigabyte (1,073,741,824)
MB_PER_GB = 1024  # Megabytes per gigabyte
TB_TO_GB_MULTIPLIER = 1000  # Convert TB to GB
PB_TO_TB_MULTIPLIER = 1000  # Convert PB to TB
MBPS_TO_GBPS_DIVISOR = 1000  # Convert Mb/s to Gb/s

_quiet: bool = False


def set_quiet(value: bool = True) -> None:
    """Enable or disable quiet mode."""
    global _quiet  # noqa: PLW0603
    _quiet = value


def is_quiet() -> bool:
    """Return whether quiet mode is active."""
    return _quiet


def is_root() -> bool:
    """Return whether running as root."""
    return os.geteuid() == 0


def ensure_root() -> None:
    """Re-exec under sudo -E if not already root."""
    if os.geteuid() == 0:
        return
    try:
        os.execvp("sudo", ["sudo", "-E", *sys.argv])
    except OSError as e:
        print_error(f"Failed to escalate to root: {e}")
        sys.exit(1)


def run_command(cmd: list[str] | str, timeout: int = COMMAND_TIMEOUT_SECONDS) -> str:
    """Execute command and return stdout, or empty string on error."""
    try:
        if isinstance(cmd, str):
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
        logger.debug("Command failed: %s — %s", cmd, e)
        return ""


def sanitize_device_name(name: str) -> str:
    """Validate and sanitize device names to prevent shell injection."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        print_warning(f"Suspicious device name detected, skipping: {name}")
        return ""
    return name


def fatal(message: str) -> NoReturn:
    """Print error and exit."""
    print_error(message)
    sys.exit(1)


def print_header(text: str) -> None:
    if is_quiet():
        return
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'=' * HEADER_WIDTH}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{text:^{HEADER_WIDTH}}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'=' * HEADER_WIDTH}{Colors.END}\n")


def print_status(emoji: str, message: str) -> None:
    if is_quiet():
        return
    print(f"{emoji} {message}")


def print_warning(message: str) -> None:
    """Print warning message (always shown)."""
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.END}")


def print_error(message: str) -> None:
    """Print error message (always shown)."""
    print(f"{Colors.RED}❌ {message}{Colors.END}")


def print_success(message: str) -> None:
    if is_quiet():
        return
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")
