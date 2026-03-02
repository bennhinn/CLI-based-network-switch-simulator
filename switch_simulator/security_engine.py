"""Security engine — port-security, DHCP snooping, DAI, 802.1X, storm control, IP source guard."""

import threading
import time
from switch_simulator.utils import format_mac, random_mac


class DHCPBinding:
    __slots__ = ("mac", "ip", "vlan", "port", "lease_time", "created")

    def __init__(self, mac, ip, vlan, port, lease_time=86400):
        self.mac = mac
        self.ip = ip
        self.vlan = vlan
        self.port = port
        self.lease_time = lease_time
        self.created = time.time()


class SecurityEngine:
    """Centralised security functions."""

    def __init__(self, switch, log_engine=None):
        self.switch = switch
        self.log = log_engine
        # Global toggles
        self.dhcp_snooping_enabled = False
        self.dhcp_snooping_vlans: set = set()
        self.dai_enabled = False
        self.dai_vlans: set = set()
        # Binding table
        self.dhcp_bindings: list[DHCPBinding] = []
        self._lock = threading.Lock()
        # err-disable recovery
        self.errdisable_recovery_enabled = True
        self.errdisable_recovery_interval = 300   # seconds
        self._recovery_thread = None
        self._running = False
        # MAC flood detection
        self.mac_flood_threshold = 50             # MACs/sec to trigger
        self._mac_learn_counts: dict = {}         # port -> count per interval
        self._last_mac_reset = time.time()
        self._dhcp_rate_windows: dict = {}        # port -> {window, count}

    # ---- Port Security checks ---------------------------------------------
    def check_port_security(self, port, mac: str) -> bool:
        """Return True if MAC is allowed, False if violation."""
        sec = port.security
        if not sec.enabled:
            return True

        # Already known sticky?
        if mac in sec.sticky_macs:
            return True

        current = self.switch.mac_table.count_by_port(port.name)
        # Check if this MAC is already learned on this port
        existing = self.switch.mac_table.macs_on_port(port.name)
        known_macs = {e.mac for e in existing}
        if mac in known_macs:
            return True

        # Over maximum?
        if current >= sec.maximum:
            self._handle_violation(port, mac)
            return False

        # If sticky, add it
        if sec.sticky:
            sec.sticky_macs.add(mac)
            if self.log:
                self.log.info("PORTSEC", "STICKY_LEARN",
                              f"Sticky MAC {format_mac(mac)} learned on {port.name}")
        return True

    def _handle_violation(self, port, mac: str):
        sec = port.security
        sec.violation_count += 1
        sec.last_violation_mac = mac
        if self.log and sec.violation_mode != "protect":
            self.log.warn("PORTSEC", "VIOLATION",
                          f"Port security violation on {port.name}: "
                          f"MAC {format_mac(mac)}, mode={sec.violation_mode}")

        if sec.violation_mode == "shutdown":
            port.set_err_disabled("psecure-violation")
            if self.log:
                self.log.error("PORTSEC", "ERR_DISABLED",
                               f"{port.name} err-disabled due to port-security violation")
        elif sec.violation_mode == "restrict":
            # Drop frame, increment counter — already done
            pass
        elif sec.violation_mode == "protect":
            # Silently drop
            pass

    # ---- DHCP Snooping ----------------------------------------------------
    def process_dhcp(self, port, mac: str, ip: str, vlan: int, is_server: bool = False):
        """Process DHCP packet. Returns True if allowed."""
        if not self.dhcp_snooping_enabled:
            return True
        if vlan not in self.dhcp_snooping_vlans:
            return True

        # Rate limit check
        if port.dhcp_snooping_rate_limit > 0:
            now = time.time()
            wnd = self._dhcp_rate_windows.get(port.name)
            if not wnd or now - wnd["window"] >= 1.0:
                wnd = {"window": now, "count": 0}
            wnd["count"] += 1
            self._dhcp_rate_windows[port.name] = wnd
            if wnd["count"] > port.dhcp_snooping_rate_limit:
                if self.log:
                    self.log.warn("DHCP_SNOOP", "RATE_LIMIT",
                                  f"DHCP snooping rate limit exceeded on {port.name}: "
                                  f"{wnd['count']} pps > {port.dhcp_snooping_rate_limit} pps")
                return False

        if is_server and not port.dhcp_snooping_trusted:
            if self.log:
                self.log.warn("DHCP_SNOOP", "UNTRUSTED_SERVER",
                              f"DHCP server response on untrusted port {port.name} — dropped")
            return False

        if not is_server and ip:
            # Add binding
            with self._lock:
                self.dhcp_bindings.append(DHCPBinding(mac, ip, vlan, port.name))
            if self.log:
                self.log.info("DHCP_SNOOP", "BINDING_ADD",
                              f"Binding: {format_mac(mac)} -> {ip} VLAN {vlan} on {port.name}")
        return True

    def get_binding(self, mac: str = None, ip: str = None):
        """Lookup DHCP binding by MAC or IP."""
        for b in self.dhcp_bindings:
            if mac and b.mac == mac:
                return b
            if ip and b.ip == ip:
                return b
        return None

    # ---- DAI (Dynamic ARP Inspection) ------------------------------------
    def check_dai(self, port, sender_mac: str, sender_ip: str, vlan: int) -> bool:
        """Return True if ARP is valid against DHCP binding table."""
        if not self.dai_enabled:
            return True
        if vlan not in self.dai_vlans:
            return True
        if port.dhcp_snooping_trusted:
            return True

        binding = self.get_binding(mac=sender_mac)
        if binding and binding.ip == sender_ip and binding.vlan == vlan:
            return True

        if self.log:
            self.log.warn("DAI", "INVALID_ARP",
                          f"Invalid ARP on {port.name}: {format_mac(sender_mac)} -> {sender_ip} "
                          f"VLAN {vlan} — no matching DHCP binding")
        return False

    # ---- IP Source Guard -------------------------------------------------
    def check_ip_source_guard(self, port, mac: str, ip: str) -> bool:
        if not port.ip_source_guard:
            return True
        binding = self.get_binding(mac=mac)
        if binding and binding.ip == ip and binding.port == port.name:
            return True
        if self.log:
            self.log.warn("IPSG", "DENIED",
                          f"IP source guard denied {format_mac(mac)}:{ip} on {port.name}")
        return False

    # ---- 802.1X helpers --------------------------------------------------
    def allow_l2_traffic(self, port, ethertype: str = "ip") -> bool:
        if not port.dot1x.enabled:
            return True
        if port.dot1x.state == "authorized":
            return True
        return ethertype.lower() in ("eap", "eapol")

    def dot1x_authenticate(self, port, success: bool = True) -> bool:
        if not port.dot1x.enabled:
            return False
        port.dot1x.state = "authorized" if success else "unauthorized"
        port.dot1x.last_auth = time.time()
        if self.log:
            if success:
                self.log.notice("DOT1X", "AUTHORIZED", f"802.1X auth success on {port.name}")
            else:
                self.log.warn("DOT1X", "UNAUTHORIZED", f"802.1X auth failed on {port.name}")
        return success

    # ---- Storm Control ---------------------------------------------------
    def check_storm_control(self, port, frame_type: str) -> bool:
        """Check storm thresholds. frame_type: broadcast|multicast|unicast."""
        sc = port.storm_control
        threshold = None
        if frame_type == "broadcast":
            threshold = sc.broadcast_level
        elif frame_type == "multicast":
            threshold = sc.multicast_level
        elif frame_type == "unicast":
            threshold = sc.unicast_level

        if threshold is None:
            return True

        # Calculate current utilization
        util = port.utilization_pct("rx")
        if util > threshold:
            if self.log:
                self.log.warn("STORM", "THRESHOLD",
                              f"Storm control {frame_type} threshold exceeded on {port.name}: "
                              f"{util:.1f}% > {threshold}%")
            if sc.action == "shutdown":
                port.set_err_disabled("storm-control")
                if self.log:
                    self.log.error("STORM", "ERR_DISABLED",
                                   f"{port.name} err-disabled due to storm-control")
            return False
        return True

    # ---- MAC Flood Detection ---------------------------------------------
    def record_mac_learn(self, port_name: str):
        """Record a MAC learn event for flood detection."""
        now = time.time()
        if now - self._last_mac_reset > 1.0:
            self._mac_learn_counts.clear()
            self._last_mac_reset = now

        self._mac_learn_counts[port_name] = self._mac_learn_counts.get(port_name, 0) + 1
        if self._mac_learn_counts[port_name] > self.mac_flood_threshold:
            if self.log:
                self.log.alert("SECURITY", "MAC_FLOOD",
                               f"MAC flooding detected on {port_name}: "
                               f"{self._mac_learn_counts[port_name]} learns/sec")
            port = self.switch.ports.get(port_name)
            if port:
                port.set_err_disabled("mac-flood")

    # ---- err-disable recovery --------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._recovery_thread = threading.Thread(target=self._recovery_loop,
                                                  daemon=True, name="ErrDisableRecovery")
        self._recovery_thread.start()

    def stop(self):
        self._running = False

    def _recovery_loop(self):
        while self._running:
            if self.errdisable_recovery_enabled:
                now = time.time()
                for port in self.switch.ports.values():
                    if port.err_disabled and port.err_disabled_time > 0:
                        elapsed = now - port.err_disabled_time
                        if elapsed >= self.errdisable_recovery_interval:
                            port.clear_err_disabled()
                            if port.admin_up:
                                port.bring_up()
                            if self.log:
                                self.log.notice("ERRDIS", "RECOVERY",
                                                f"{port.name} recovered from err-disabled "
                                                f"(was: {port.err_disabled_reason})")
            time.sleep(10)

    # ---- show commands ----------------------------------------------------
    def show_port_security(self, port=None) -> str:
        lines = []
        if port:
            s = port.security
            lines.append(f"Port Security              : {'Enabled' if s.enabled else 'Disabled'}")
            lines.append(f"Port Status                : {'Secure-up' if port.is_up else 'Secure-down'}")
            lines.append(f"Violation Mode             : {s.violation_mode.capitalize()}")
            lines.append(f"Maximum MAC Addresses      : {s.maximum}")
            lines.append(f"Total MAC Addresses        : {self.switch.mac_table.count_by_port(port.name)}")
            lines.append(f"Sticky MAC Addresses       : {len(s.sticky_macs)}")
            lines.append(f"Security Violation Count   : {s.violation_count}")
            if s.last_violation_mac:
                lines.append(f"Last Violation MAC         : {format_mac(s.last_violation_mac)}")
        else:
            lines.append(f"{'Port':<22s} {'MaxSecureAddr':<16s} {'CurrentAddr':<14s} "
                          f"{'SecurityViolation':<18s} {'Security Action'}")
            lines.append("-" * 90)
            for pname in sorted(self.switch.ports):
                p = self.switch.ports[pname]
                if not p.security.enabled:
                    continue
                cnt = self.switch.mac_table.count_by_port(p.name)
                lines.append(
                    f"{p.short_name:<22s} {p.security.maximum:<16d} {cnt:<14d} "
                    f"{p.security.violation_count:<18d} {p.security.violation_mode.capitalize()}"
                )
        return "\n".join(lines)

    def show_dhcp_snooping_binding(self) -> str:
        lines = []
        lines.append(f"{'MacAddress':<18s} {'IpAddress':<16s} {'Lease(sec)':<12s} "
                      f"{'Type':<10s} {'VLAN':<6s} Interface")
        lines.append("-" * 80)
        for b in self.dhcp_bindings:
            remaining = max(0, int(b.lease_time - (time.time() - b.created)))
            lines.append(
                f"{format_mac(b.mac):<18s} {b.ip:<16s} {remaining:<12d} "
                f"{'dhcp-snooping':<10s} {b.vlan:<6d} {b.port}"
            )
        lines.append(f"Total number of bindings: {len(self.dhcp_bindings)}")
        return "\n".join(lines)

    def show_errdisable_recovery(self) -> str:
        lines = []
        lines.append(f"ErrDisable Recovery  : {'Enabled' if self.errdisable_recovery_enabled else 'Disabled'}")
        lines.append(f"Recovery Interval    : {self.errdisable_recovery_interval} seconds")
        lines.append("")
        lines.append(f"{'Interface':<22s} {'Reason':<24s} {'Time Remaining'}")
        lines.append("-" * 60)
        now = time.time()
        for pname in sorted(self.switch.ports):
            p = self.switch.ports[pname]
            if p.err_disabled:
                remaining = max(0, int(self.errdisable_recovery_interval -
                                        (now - p.err_disabled_time)))
                lines.append(f"{p.short_name:<22s} {p.err_disabled_reason:<24s} {remaining}s")
        return "\n".join(lines)

    def show_storm_control(self) -> str:
        lines = []
        lines.append(f"{'Interface':<22s} {'Filter':<12s} {'Level':<10s} {'Action'}")
        lines.append("-" * 56)
        for pname in sorted(self.switch.ports):
            p = self.switch.ports[pname]
            sc = p.storm_control
            for ftype, level in [("Broadcast", sc.broadcast_level),
                                  ("Multicast", sc.multicast_level),
                                  ("Unicast", sc.unicast_level)]:
                if level is not None:
                    lines.append(f"{p.short_name:<22s} {ftype:<12s} {level:<10.1f} {sc.action}")
        return "\n".join(lines)

    # ---- serialization ---------------------------------------------------
    def to_dict(self):
        return {
            "dhcp_snooping_enabled": self.dhcp_snooping_enabled,
            "dhcp_snooping_vlans": sorted(self.dhcp_snooping_vlans),
            "dai_enabled": self.dai_enabled,
            "dai_vlans": sorted(self.dai_vlans),
            "errdisable_recovery_enabled": self.errdisable_recovery_enabled,
            "errdisable_recovery_interval": self.errdisable_recovery_interval,
            "mac_flood_threshold": self.mac_flood_threshold,
            "dhcp_bindings": [{"mac": b.mac, "ip": b.ip, "vlan": b.vlan,
                               "port": b.port, "lease": b.lease_time}
                              for b in self.dhcp_bindings],
        }

    def from_dict(self, data):
        self.dhcp_snooping_enabled = data.get("dhcp_snooping_enabled", False)
        self.dhcp_snooping_vlans = set(data.get("dhcp_snooping_vlans", []))
        self.dai_enabled = data.get("dai_enabled", False)
        self.dai_vlans = set(data.get("dai_vlans", []))
        self.errdisable_recovery_enabled = data.get("errdisable_recovery_enabled", True)
        self.errdisable_recovery_interval = data.get("errdisable_recovery_interval", 300)
        self.mac_flood_threshold = data.get("mac_flood_threshold", 50)
        self.dhcp_bindings.clear()
        for bd in data.get("dhcp_bindings", []):
            self.dhcp_bindings.append(
                DHCPBinding(bd["mac"], bd["ip"], bd["vlan"], bd["port"], bd.get("lease", 86400))
            )
