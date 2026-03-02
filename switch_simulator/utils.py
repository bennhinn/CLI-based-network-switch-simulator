"""Utility functions, color helpers, and constants for the switch simulator."""

import re
import time
import random
from datetime import datetime

# ---------------------------------------------------------------------------
# Color support (colorama)
# ---------------------------------------------------------------------------
try:
    from colorama import init as _colorama_init, Fore, Style
    _colorama_init(autoreset=True)
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


class Colors:
    """Terminal color shortcuts."""
    if _HAS_COLOR:
        OK = Fore.GREEN
        WARN = Fore.YELLOW
        ERR = Fore.RED
        INFO = Fore.CYAN
        BOLD = Style.BRIGHT
        DIM = Style.DIM
        RESET = Style.RESET_ALL
    else:
        OK = WARN = ERR = INFO = BOLD = DIM = RESET = ""


def green(t):  return f"{Colors.OK}{t}{Colors.RESET}"
def yellow(t): return f"{Colors.WARN}{t}{Colors.RESET}"
def red(t):    return f"{Colors.ERR}{t}{Colors.RESET}"
def cyan(t):   return f"{Colors.INFO}{t}{Colors.RESET}"
def bold(t):   return f"{Colors.BOLD}{t}{Colors.RESET}"
def dim(t):    return f"{Colors.DIM}{t}{Colors.RESET}"


# ---------------------------------------------------------------------------
# MAC / IP formatting
# ---------------------------------------------------------------------------
def format_mac(mac: str) -> str:
    """Return Cisco-style xxxx.xxxx.xxxx."""
    m = mac.replace(":", "").replace("-", "").replace(".", "").lower()
    if len(m) != 12:
        return mac
    return f"{m[0:4]}.{m[4:8]}.{m[8:12]}"


def parse_mac(mac_str: str):
    """Normalise any MAC format to 12-char hex or None."""
    m = mac_str.replace(":", "").replace("-", "").replace(".", "").lower()
    if len(m) == 12 and all(c in "0123456789abcdef" for c in m):
        return m
    return None


def random_mac(oui="aa:bb:cc"):
    """Generate a random MAC with a given OUI prefix."""
    oui_hex = oui.replace(":", "").replace("-", "").replace(".", "").lower()
    suffix = "".join(random.choice("0123456789abcdef") for _ in range(12 - len(oui_hex)))
    full = oui_hex + suffix
    return format_mac(full)


def format_ip(octets):
    return ".".join(str(o) for o in octets)


# ---------------------------------------------------------------------------
# Uptime / bandwidth formatting
# ---------------------------------------------------------------------------
def format_uptime(seconds: float) -> str:
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    parts = []
    if d:
        parts.append(f"{d} day{'s' if d != 1 else ''}")
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    parts.append(f"{s} second{'s' if s != 1 else ''}")
    return ", ".join(parts)


def format_bytes(b):
    if b >= 1_000_000_000:
        return f"{b / 1e9:.2f} GB"
    if b >= 1_000_000:
        return f"{b / 1e6:.2f} MB"
    if b >= 1_000:
        return f"{b / 1e3:.2f} KB"
    return f"{b} bytes"


def format_bps(bps):
    if bps >= 1_000_000_000:
        return f"{bps / 1e9:.1f} Gbps"
    if bps >= 1_000_000:
        return f"{bps / 1e6:.1f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1e3:.1f} Kbps"
    return f"{bps:.0f} bps"


# ---------------------------------------------------------------------------
# Interface name parsing (abbreviation-aware)
# ---------------------------------------------------------------------------
_INTF_ABBREVS = {
    "fa": "FastEthernet",
    "fastethernet": "FastEthernet",
    "gi": "GigabitEthernet",
    "gig": "GigabitEthernet",
    "gigabitethernet": "GigabitEthernet",
    "te": "TenGigabitEthernet",
    "tengig": "TenGigabitEthernet",
    "tengigabitethernet": "TenGigabitEthernet",
    "po": "Port-channel",
    "port-channel": "Port-channel",
    "vl": "Vlan",
    "vlan": "Vlan",
    "lo": "Loopback",
    "loopback": "Loopback",
}


def parse_interface_name(name: str):
    """Return (full_type, number_str) or None."""
    name = name.strip()
    m = re.match(r"^([a-zA-Z-]+)\s*(\d+(?:/\d+)*)$", name)
    if not m:
        return None
    prefix = m.group(1).lower()
    number = m.group(2)
    # exact match first
    if prefix in _INTF_ABBREVS:
        return (_INTF_ABBREVS[prefix], number)
    # prefix match
    for abbr, full in _INTF_ABBREVS.items():
        if abbr.startswith(prefix):
            return (full, number)
    return None


def canonical_intf(name: str) -> str:
    """Return canonical interface name like GigabitEthernet0/1."""
    parsed = parse_interface_name(name)
    if parsed:
        itype, number = parsed
        if itype == "FastEthernet":
            itype = "GigabitEthernet"
        return f"{itype}{number}"
    return name


def short_intf(name: str) -> str:
    """Shorten GigabitEthernet0/1 -> Gi0/1."""
    shorts = {
        "GigabitEthernet": "Gi",
        "TenGigabitEthernet": "Te",
        "Port-channel": "Po",
        "Vlan": "Vl",
        "Loopback": "Lo",
    }
    for full, sh in shorts.items():
        if name.startswith(full):
            return sh + name[len(full):]
    return name


def parse_vlan_list(vlan_str: str):
    """Parse '1,10-20,30' into a set of VLAN IDs."""
    vlans = set()
    for part in vlan_str.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                for v in range(int(lo), int(hi) + 1):
                    if 1 <= v <= 4094:
                        vlans.add(v)
            except ValueError:
                pass
        else:
            try:
                v = int(part)
                if 1 <= v <= 4094:
                    vlans.add(v)
            except ValueError:
                pass
    return vlans


# ---------------------------------------------------------------------------
# Cisco-style error formatting
# ---------------------------------------------------------------------------
def ios_error(cmd: str, pos: int = 0) -> str:
    return f"% Invalid input detected at '^' marker.\n{cmd}\n{' ' * pos}^"


def ios_incomplete():
    return "% Incomplete command."


# ---------------------------------------------------------------------------
# Command explanation database
# ---------------------------------------------------------------------------
EXPLANATIONS = {
    "show running-config": "Displays the current active configuration stored in RAM. Changes made in config mode appear here immediately.",
    "show startup-config": "Displays the saved configuration in NVRAM that loads at boot. Use 'write memory' to sync running-config here.",
    "show interfaces": "Displays detailed statistics for all interfaces including rx/tx counters, errors, speed, duplex, and line protocol status.",
    "show interfaces status": "Displays a summary table of all interfaces with status, VLAN, duplex, speed, and type.",
    "show interfaces trunk": "Displays all trunk ports with their native VLAN and allowed VLAN lists.",
    "show vlan": "Displays the VLAN database showing VLAN IDs, names, status, and assigned ports.",
    "show vlan brief": "Displays a compact summary of the VLAN database.",
    "show mac address-table": "Displays the MAC address forwarding table used for Layer 2 switching decisions.",
    "show spanning-tree": "Displays STP topology information including root bridge, port roles, and port states.",
    "show port-security": "Displays port security status showing violation counts, secure MAC addresses, and security modes.",
    "show power inline": "Displays PoE power status for all ports including power drawn, device class, and budget remaining.",
    "show ip arp": "Displays the ARP table mapping IP addresses to MAC addresses.",
    "show cdp neighbors": "Displays directly connected Cisco devices discovered via CDP.",
    "show lldp neighbors": "Displays directly connected devices discovered via LLDP (IEEE 802.1AB).",
    "show etherchannel summary": "Displays a summary of all port-channel groups and their member interfaces.",
    "show dhcp snooping binding": "Displays the DHCP snooping binding table (MAC, IP, VLAN, interface mappings).",
    "show monitor session": "Displays SPAN/RSPAN port mirroring session configuration.",
    "show logging": "Displays the syslog buffer with timestamped event messages.",
    "show ip interface brief": "Displays a brief summary of all IP-enabled interfaces with status.",
    "show version": "Displays system hardware and software status including uptime and model.",
    "show errdisable recovery": "Displays err-disable recovery timer settings and currently disabled interfaces.",
    "show storm-control": "Displays storm control thresholds and actions per interface.",
    "configure terminal": "Enters global configuration mode where you can modify the switch configuration.",
    "write memory": "Saves the running configuration to startup-config in NVRAM (persists across reboot).",
    "copy running-config startup-config": "Same as 'write memory' — copies active config to NVRAM.",
    "erase startup-config": "Deletes the startup configuration. Next reload will use factory defaults.",
    "reload": "Restarts the switch. Unsaved running-config changes will be lost.",
    "switchport mode access": "Configures the port as an access port carrying a single VLAN for end devices.",
    "switchport mode trunk": "Configures the port as a trunk carrying multiple VLANs using 802.1Q tagging.",
    "switchport port-security": "Enables port security to limit MAC addresses learned on a port.",
    "port-security violation shutdown": "When the secure MAC limit is exceeded, the port is put into err-disabled state and must be manually or automatically recovered.",
    "spanning-tree mode rapid-pvst": "Sets STP to Rapid Per-VLAN Spanning Tree Plus for faster convergence.",
    "shutdown": "Administratively disables the interface. No traffic will pass.",
    "no shutdown": "Administratively enables the interface, allowing it to come up.",
    "channel-group": "Assigns the interface to a port-channel bundle for link aggregation.",
    "ip dhcp snooping": "Enables DHCP snooping globally to protect against rogue DHCP servers.",
    "ip arp inspection": "Enables Dynamic ARP Inspection to validate ARP packets against the DHCP snooping binding table.",
    "storm-control": "Configures traffic storm thresholds to suppress broadcast/multicast/unicast storms.",
    "dot1x": "Configures 802.1X port-based network access control for authentication.",
}

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def ios_timestamp():
    """Return IOS-style timestamp like *Mar  2 14:30:01.123"""
    now = datetime.now()
    return now.strftime("*%b %d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"

def epoch():
    return time.time()
