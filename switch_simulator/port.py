"""Port model — represents a single physical or logical switch port."""

import time
import threading
import random
from switch_simulator.utils import format_mac, random_mac, canonical_intf, short_intf


class PortStats:
    """Traffic statistics for a port."""
    __slots__ = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
                 "rx_errors", "tx_errors", "rx_crc", "rx_late_collisions",
                 "rx_broadcast", "tx_broadcast", "rx_multicast", "tx_multicast",
                 "input_rate_bps", "output_rate_bps", "link_flaps")

    def __init__(self):
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.rx_packets = 0
        self.tx_packets = 0
        self.rx_errors = 0
        self.tx_errors = 0
        self.rx_crc = 0
        self.rx_late_collisions = 0
        self.rx_broadcast = 0
        self.tx_broadcast = 0
        self.rx_multicast = 0
        self.tx_multicast = 0
        self.input_rate_bps = 0
        self.output_rate_bps = 0
        self.link_flaps = 0


class PortSecurity:
    """Port-security sub-config."""
    __slots__ = ("enabled", "maximum", "violation_mode", "sticky",
                 "sticky_macs", "violation_count", "last_violation_mac")

    def __init__(self):
        self.enabled = False
        self.maximum = 1
        self.violation_mode = "shutdown"     # shutdown | restrict | protect
        self.sticky = False
        self.sticky_macs: set = set()        # set of normalised MACs
        self.violation_count = 0
        self.last_violation_mac = ""


class StormControl:
    """Storm-control per-port config."""
    __slots__ = ("broadcast_level", "multicast_level", "unicast_level",
                 "action")

    def __init__(self):
        self.broadcast_level = None    # percent threshold or None = off
        self.multicast_level = None
        self.unicast_level = None
        self.action = "shutdown"       # shutdown | trap


class Dot1xConfig:
    """802.1X config per port."""
    __slots__ = ("enabled", "state", "guest_vlan", "reauth_timer", "last_auth")

    def __init__(self):
        self.enabled = False
        self.state = "unauthorized"    # unauthorized | authorized | guest
        self.guest_vlan = None
        self.reauth_timer = 3600
        self.last_auth = 0.0


class Port:
    """Represents a physical or logical switch interface."""

    def __init__(self, name: str, speed: int = 1_000_000_000, port_type: str = "GE"):
        self.name = name                         # e.g. GigabitEthernet0/1
        self.short_name = short_intf(name)
        self.speed = speed                       # bps
        self.port_type = port_type               # GE | 10GE
        self.description = ""
        self.admin_up = True
        self.link_up = False
        self.line_protocol = "down"
        self.err_disabled = False
        self.err_disabled_reason = ""
        self.err_disabled_time = 0.0

        # L2 config
        self.switchport_mode = "access"          # access | trunk
        self.access_vlan = 1
        self.voice_vlan = None
        self.trunk_native_vlan = 1
        self.trunk_allowed_vlans: set = set(range(1, 4095))
        self.trunk_encapsulation = "dot1q"

        # STP
        self.stp_port_priority = 128
        self.stp_port_cost = None                # auto-derived from speed
        self.stp_role = "designated"             # root | designated | alternate | backup
        self.stp_state = "forwarding"            # disabled | blocking | listening | learning | forwarding
        self.bpdu_guard = False
        self.root_guard = False
        self.portfast = False

        # Security
        self.security = PortSecurity()
        self.storm_control = StormControl()
        self.dot1x = Dot1xConfig()
        self.dhcp_snooping_trusted = False
        self.dhcp_snooping_rate_limit = 0        # pps, 0 = unlimited
        self.ip_source_guard = False

        # PoE
        self.poe_enabled = True
        self.poe_allocated_w = 0.0
        self.poe_device_class = None             # 0–8
        self.poe_device_type = ""                # e.g. "IP Phone"
        self.poe_priority = "low"                # critical | high | low
        self.poe_max_w = 0.0

        # Port-channel
        self.channel_group = None                # int or None
        self.channel_protocol = None             # lacp | pagp | None

        # SPAN
        self.span_source = False
        self.span_destination = False
        self.span_session = None

        # CDP / LLDP neighbour info (simulated)
        self.cdp_neighbor = None                 # dict or None
        self.lldp_neighbor = None

        # QoS
        self.qos_trust = None                    # cos | dscp | None
        self.qos_default_cos = 0
        self.qos_queues = {i: {"packets": 0, "drops": 0} for i in range(8)}

        # Stats
        self.stats = PortStats()
        self._lock = threading.Lock()
        self._up_since = 0.0

        # MAC address of the port itself
        self.hw_addr = random_mac("00:aa:bb")

    # ---- helpers -----------------------------------------------------------
    @property
    def is_up(self):
        return self.admin_up and self.link_up and not self.err_disabled

    @property
    def status_str(self):
        if self.err_disabled:
            return "err-disabled"
        if not self.admin_up:
            return "disabled"
        if not self.link_up:
            return "notconnect"
        return "connected"

    @property
    def duplex_str(self):
        if not self.is_up:
            return "auto"
        return "a-full"

    @property
    def speed_str(self):
        if not self.is_up:
            return "auto"
        if self.speed >= 10_000_000_000:
            return "a-10G"
        return "a-1000"

    @property
    def media_type(self):
        if self.port_type == "10GE":
            return "10GBase-SR"
        return "10/100/1000BaseTX"

    def stp_cost(self):
        if self.stp_port_cost is not None:
            return self.stp_port_cost
        if self.speed >= 10_000_000_000:
            return 2
        if self.speed >= 1_000_000_000:
            return 4
        if self.speed >= 100_000_000:
            return 19
        return 100

    def bring_up(self):
        self.link_up = True
        self.line_protocol = "up"
        self._up_since = time.time()

    def bring_down(self):
        self.link_up = False
        self.line_protocol = "down"
        self.stats.link_flaps += 1

    def set_err_disabled(self, reason: str):
        self.err_disabled = True
        self.err_disabled_reason = reason
        self.link_up = False
        self.line_protocol = "down (err-disabled)"
        self.err_disabled_time = time.time()

    def clear_err_disabled(self):
        self.err_disabled = False
        self.err_disabled_reason = ""
        self.err_disabled_time = 0.0
        self.line_protocol = "down"

    def utilization_pct(self, direction="rx"):
        if self.speed == 0:
            return 0.0
        rate = self.stats.input_rate_bps if direction == "rx" else self.stats.output_rate_bps
        return min(100.0, (rate / self.speed) * 100.0)

    # ---- show interfaces ---------------------------------------------------
    def show_interface(self) -> str:
        state = "up" if self.is_up else "down"
        proto = self.line_protocol
        lines = []
        lines.append(f"{self.name} is {state}, line protocol is {proto}")
        if self.description:
            lines.append(f"  Description: {self.description}")
        lines.append(f"  Hardware is {self.media_type}, address is {self.hw_addr}")
        lines.append(f"  MTU 1500 bytes, BW {self.speed // 1000} Kbit/sec, DLY 10 usec,")
        lines.append(f"     reliability 255/255, txload 1/255, rxload 1/255")
        lines.append(f"  Encapsulation ARPA, loopback not set")
        if self.switchport_mode == "trunk":
            lines.append(f"  Trunk encapsulation {self.trunk_encapsulation}, "
                         f"native VLAN {self.trunk_native_vlan}")
        else:
            lines.append(f"  Switchport mode access, access VLAN {self.access_vlan}")
        lines.append(f"  Full-duplex, {self.speed // 1_000_000}Mb/s, link type is auto")
        lines.append(f"  input flow-control is off, output flow-control is unsupported")
        lines.append(f"  Last input never, output never, output hang never")
        lines.append(f"  Last clearing of \"show interface\" counters never")
        lines.append(f"  Input queue: 0/75/0/0 (size/max/drops/flushes)")
        lines.append(f"  5 minute input rate {self.stats.input_rate_bps} bits/sec, "
                      f"{self.stats.rx_packets} packets/sec")
        lines.append(f"  5 minute output rate {self.stats.output_rate_bps} bits/sec, "
                      f"{self.stats.tx_packets} packets/sec")
        lines.append(f"     {self.stats.rx_packets} packets input, {self.stats.rx_bytes} bytes, 0 no buffer")
        lines.append(f"     Received {self.stats.rx_broadcast} broadcasts ({self.stats.rx_multicast} multicasts)")
        lines.append(f"     {self.stats.rx_errors} input errors, {self.stats.rx_crc} CRC, 0 frame, "
                      f"0 overrun, 0 ignored")
        lines.append(f"     {self.stats.tx_packets} packets output, {self.stats.tx_bytes} bytes, 0 underruns")
        lines.append(f"     {self.stats.tx_errors} output errors, {self.stats.rx_late_collisions} "
                      f"collisions, 0 interface resets")
        lines.append(f"     {self.stats.link_flaps} link flaps")
        return "\n".join(lines)

    def show_status_line(self) -> str:
        """One-line for show interfaces status."""
        vlan_str = str(self.access_vlan) if self.switchport_mode == "access" else "trunk"
        if self.err_disabled:
            vlan_str = "err-disabled"
        return (
            f"{self.short_name:<18s}  "
            f"{self.description[:18]:<18s}  "
            f"{self.status_str:<12s}  "
            f"{vlan_str:<8s}  "
            f"{self.duplex_str:<8s}  "
            f"{self.speed_str:<8s}  "
            f"{self.media_type}"
        )

    # ---- serialization ----------------------------------------------------
    def to_config_lines(self) -> list[str]:
        """Generate running-config lines for this interface."""
        lines = [f"interface {self.name}"]
        if self.description:
            lines.append(f" description {self.description}")
        if not self.admin_up:
            lines.append(" shutdown")
        if self.switchport_mode == "trunk":
            lines.append(" switchport mode trunk")
            lines.append(f" switchport trunk native vlan {self.trunk_native_vlan}")
            if self.trunk_allowed_vlans != set(range(1, 4095)):
                vstr = self._compress_vlan_set(self.trunk_allowed_vlans)
                lines.append(f" switchport trunk allowed vlan {vstr}")
        else:
            lines.append(" switchport mode access")
            lines.append(f" switchport access vlan {self.access_vlan}")
        if self.voice_vlan:
            lines.append(f" switchport voice vlan {self.voice_vlan}")
        if self.security.enabled:
            lines.append(" switchport port-security")
            lines.append(f" switchport port-security maximum {self.security.maximum}")
            lines.append(f" switchport port-security violation {self.security.violation_mode}")
            if self.security.sticky:
                lines.append(" switchport port-security mac-address sticky")
                for m in sorted(self.security.sticky_macs):
                    lines.append(f" switchport port-security mac-address sticky {format_mac(m)}")
        if self.portfast:
            lines.append(" spanning-tree portfast")
        if self.bpdu_guard:
            lines.append(" spanning-tree bpduguard enable")
        if self.root_guard:
            lines.append(" spanning-tree guard root")
        if self.storm_control.broadcast_level is not None:
            lines.append(f" storm-control broadcast level {self.storm_control.broadcast_level}")
        if self.storm_control.multicast_level is not None:
            lines.append(f" storm-control multicast level {self.storm_control.multicast_level}")
        if self.storm_control.unicast_level is not None:
            lines.append(f" storm-control unicast level {self.storm_control.unicast_level}")
        if self.storm_control.action != "shutdown":
            lines.append(f" storm-control action {self.storm_control.action}")
        if self.dot1x.enabled:
            lines.append(" dot1x port-control auto")
            if self.dot1x.guest_vlan:
                lines.append(f" dot1x guest-vlan {self.dot1x.guest_vlan}")
        if self.dhcp_snooping_trusted:
            lines.append(" ip dhcp snooping trust")
        if self.dhcp_snooping_rate_limit:
            lines.append(f" ip dhcp snooping limit rate {self.dhcp_snooping_rate_limit}")
        if self.ip_source_guard:
            lines.append(" ip verify source")
        if self.qos_trust:
            lines.append(f" mls qos trust {self.qos_trust}")
        if self.channel_group is not None:
            proto = f" mode {self.channel_protocol}" if self.channel_protocol else ""
            lines.append(f" channel-group {self.channel_group}{proto}")
        if self.poe_priority != "low":
            lines.append(f" power inline priority {self.poe_priority}")
        if not self.poe_enabled:
            lines.append(" power inline never")
        if self.span_source:
            lines.append(f" ! SPAN source (session {self.span_session})")
        if self.span_destination:
            lines.append(f" ! SPAN destination (session {self.span_session})")
        lines.append("!")
        return lines

    @staticmethod
    def _compress_vlan_set(vlans: set) -> str:
        if not vlans:
            return "none"
        sorted_v = sorted(vlans)
        ranges = []
        start = prev = sorted_v[0]
        for v in sorted_v[1:]:
            if v == prev + 1:
                prev = v
            else:
                ranges.append(f"{start}-{prev}" if start != prev else str(start))
                start = prev = v
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        return ",".join(ranges)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "admin_up": self.admin_up,
            "switchport_mode": self.switchport_mode,
            "access_vlan": self.access_vlan,
            "voice_vlan": self.voice_vlan,
            "trunk_native_vlan": self.trunk_native_vlan,
            "trunk_allowed_vlans": sorted(self.trunk_allowed_vlans),
            "portfast": self.portfast,
            "bpdu_guard": self.bpdu_guard,
            "root_guard": self.root_guard,
            "security_enabled": self.security.enabled,
            "security_max": self.security.maximum,
            "security_violation": self.security.violation_mode,
            "security_sticky": self.security.sticky,
            "security_sticky_macs": sorted(self.security.sticky_macs),
            "poe_enabled": self.poe_enabled,
            "poe_priority": self.poe_priority,
            "channel_group": self.channel_group,
            "channel_protocol": self.channel_protocol,
            "qos_trust": self.qos_trust,
            "storm_broadcast": self.storm_control.broadcast_level,
            "storm_multicast": self.storm_control.multicast_level,
            "storm_unicast": self.storm_control.unicast_level,
            "storm_action": self.storm_control.action,
            "dot1x_enabled": self.dot1x.enabled,
            "dot1x_guest_vlan": self.dot1x.guest_vlan,
            "dhcp_trust": self.dhcp_snooping_trusted,
            "dhcp_rate_limit": self.dhcp_snooping_rate_limit,
            "ip_source_guard": self.ip_source_guard,
        }

    def from_dict(self, data: dict):
        self.description = data.get("description", "")
        self.admin_up = data.get("admin_up", True)
        self.switchport_mode = data.get("switchport_mode", "access")
        self.access_vlan = data.get("access_vlan", 1)
        self.voice_vlan = data.get("voice_vlan")
        self.trunk_native_vlan = data.get("trunk_native_vlan", 1)
        self.trunk_allowed_vlans = set(data.get("trunk_allowed_vlans", range(1, 4095)))
        self.portfast = data.get("portfast", False)
        self.bpdu_guard = data.get("bpdu_guard", False)
        self.root_guard = data.get("root_guard", False)
        self.security.enabled = data.get("security_enabled", False)
        self.security.maximum = data.get("security_max", 1)
        self.security.violation_mode = data.get("security_violation", "shutdown")
        self.security.sticky = data.get("security_sticky", False)
        self.security.sticky_macs = set(data.get("security_sticky_macs", []))
        self.poe_enabled = data.get("poe_enabled", True)
        self.poe_priority = data.get("poe_priority", "low")
        self.channel_group = data.get("channel_group")
        self.channel_protocol = data.get("channel_protocol")
        self.qos_trust = data.get("qos_trust")
        self.storm_control.broadcast_level = data.get("storm_broadcast")
        self.storm_control.multicast_level = data.get("storm_multicast")
        self.storm_control.unicast_level = data.get("storm_unicast")
        self.storm_control.action = data.get("storm_action", "shutdown")
        self.dot1x.enabled = data.get("dot1x_enabled", False)
        self.dot1x.guest_vlan = data.get("dot1x_guest_vlan")
        self.dhcp_snooping_trusted = data.get("dhcp_trust", False)
        self.dhcp_snooping_rate_limit = data.get("dhcp_rate_limit", 0)
        self.ip_source_guard = data.get("ip_source_guard", False)
