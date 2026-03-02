"""Attack simulation module — MAC flood, ARP spoof, DHCP starvation."""

import time
import threading
import random
from switch_simulator.utils import format_mac, random_mac, Colors


class AttackSimulator:
    """Simulate various L2 attacks with real-time log output."""

    def __init__(self, switch, log_engine=None):
        self.switch = switch
        self.log = log_engine

    def run_attack(self, attack_type: str, **kwargs) -> str:
        """Execute an attack scenario. Returns summary."""
        attacks = {
            "mac-flood": self._mac_flood,
            "arp-spoof": self._arp_spoof,
            "dhcp-starvation": self._dhcp_starvation,
        }
        func = attacks.get(attack_type)
        if not func:
            return f"% Unknown attack type '{attack_type}'. Available: {', '.join(attacks.keys())}"
        return func(**kwargs)

    def _mac_flood(self, port_name: str = None, count: int = 200, **kw) -> str:
        """Simulate MAC address table overflow attack."""
        if not port_name:
            # pick first access port
            for p in self.switch.ports.values():
                if p.switchport_mode == "access" and p.is_up:
                    port_name = p.name
                    break
        if not port_name:
            return "% No suitable port for MAC flood simulation."

        port = self.switch.ports.get(port_name)
        if not port:
            return f"% Port {port_name} not found."

        if self.log:
            self.log.alert("ATTACK", "MAC_FLOOD_START",
                           f"MAC flood attack simulation on {port_name}: {count} MACs")

        blocked = 0
        learned = 0
        for i in range(count):
            fake_mac = random_mac(f"{random.randint(0,255):02x}:{random.randint(0,255):02x}:00")
            vlan = port.access_vlan

            # Check port security
            if port.security.enabled:
                allowed = self.switch.security_engine.check_port_security(port, fake_mac)
                if not allowed:
                    blocked += 1
                    if port.err_disabled:
                        if self.log:
                            self.log.alert("ATTACK", "MAC_FLOOD_SHUTDOWN",
                                           f"Port {port_name} shut down by port-security after "
                                           f"{i+1} MACs ({blocked} violations)")
                        break
                    continue

            # MAC flood detection
            self.switch.security_engine.record_mac_learn(port_name)
            if port.err_disabled:
                if self.log:
                    self.log.alert("ATTACK", "MAC_FLOOD_DETECTED",
                                   f"MAC flood detected and port {port_name} disabled after {i+1} MACs")
                break

            self.switch.mac_table.learn(fake_mac, vlan, port_name)
            learned += 1

            if (i + 1) % 50 == 0 and self.log:
                self.log.info("ATTACK", "MAC_FLOOD_PROGRESS",
                              f"Injected {i+1}/{count} MACs on {port_name}")
            time.sleep(0.005)  # small delay for realism

        result = (f"MAC Flood Summary:\n"
                  f"  Target port: {port_name}\n"
                  f"  MACs attempted: {count}\n"
                  f"  MACs learned: {learned}\n"
                  f"  Violations: {blocked}\n"
                  f"  Port err-disabled: {'YES' if port.err_disabled else 'NO'}\n"
                  f"  MAC table size: {self.switch.mac_table.count()}/{self.switch.mac_table.MAX_ENTRIES}")

        if self.log:
            self.log.alert("ATTACK", "MAC_FLOOD_END", f"MAC flood complete: {learned} learned, {blocked} blocked")
        return result

    def _arp_spoof(self, target_ip: str = "192.168.1.1",
                   spoofed_mac: str = None, port_name: str = None, count: int = 20, **kw) -> str:
        """Simulate ARP spoofing attack."""
        if not spoofed_mac:
            spoofed_mac = random_mac("de:ad:be")
        spoofed_mac_norm = spoofed_mac.replace(":", "").replace("-", "").replace(".", "").lower()

        if not port_name:
            for p in self.switch.ports.values():
                if p.switchport_mode == "access" and p.is_up:
                    port_name = p.name
                    break
        if not port_name:
            return "% No suitable port for ARP spoof simulation."

        port = self.switch.ports.get(port_name)
        if not port:
            return f"% Port {port_name} not found."

        if self.log:
            self.log.alert("ATTACK", "ARP_SPOOF_START",
                           f"ARP spoof attack: claiming {target_ip} is at "
                           f"{format_mac(spoofed_mac_norm)} via {port_name}")

        blocked = 0
        passed = 0
        for i in range(count):
            vlan = port.access_vlan
            # Check DAI
            if not self.switch.security_engine.check_dai(port, spoofed_mac_norm, target_ip, vlan):
                blocked += 1
            else:
                passed += 1
                # Poison ARP table
                self.switch.arp_table.add(target_ip, spoofed_mac_norm, vlan, port_name)

            time.sleep(0.05)

        result = (f"ARP Spoof Summary:\n"
                  f"  Target IP: {target_ip}\n"
                  f"  Spoofed MAC: {format_mac(spoofed_mac_norm)}\n"
                  f"  Port: {port_name}\n"
                  f"  ARP replies sent: {count}\n"
                  f"  Passed (poisoned): {passed}\n"
                  f"  Blocked by DAI: {blocked}\n"
                  f"  DAI enabled: {'YES' if self.switch.security_engine.dai_enabled else 'NO'}")

        if self.log:
            self.log.alert("ATTACK", "ARP_SPOOF_END",
                           f"ARP spoof complete: {passed} passed, {blocked} blocked by DAI")
        return result

    def _dhcp_starvation(self, port_name: str = None, count: int = 50, **kw) -> str:
        """Simulate DHCP starvation attack."""
        if not port_name:
            for p in self.switch.ports.values():
                if p.switchport_mode == "access" and p.is_up:
                    port_name = p.name
                    break
        if not port_name:
            return "% No suitable port for DHCP starvation simulation."

        port = self.switch.ports.get(port_name)
        if not port:
            return f"% Port {port_name} not found."

        if self.log:
            self.log.alert("ATTACK", "DHCP_STARV_START",
                           f"DHCP starvation attack on {port_name}: {count} requests")

        blocked = 0
        obtained = 0
        for i in range(count):
            fake_mac = random_mac(f"{random.randint(0,255):02x}:fa:ke")
            fake_ip = f"192.168.{random.randint(1,254)}.{random.randint(2,254)}"
            vlan = port.access_vlan

            # Check port security first
            if port.security.enabled:
                allowed = self.switch.security_engine.check_port_security(port, fake_mac)
                if not allowed:
                    blocked += 1
                    if port.err_disabled:
                        break
                    continue

            # DHCP snooping check
            allowed = self.switch.security_engine.process_dhcp(
                port, fake_mac, fake_ip, vlan, is_server=False)
            if allowed:
                obtained += 1
            else:
                blocked += 1

            time.sleep(0.02)

        result = (f"DHCP Starvation Summary:\n"
                  f"  Port: {port_name}\n"
                  f"  DHCP requests sent: {count}\n"
                  f"  Leases obtained: {obtained}\n"
                  f"  Blocked: {blocked}\n"
                  f"  Port err-disabled: {'YES' if port.err_disabled else 'NO'}\n"
                  f"  DHCP snooping enabled: "
                  f"{'YES' if self.switch.security_engine.dhcp_snooping_enabled else 'NO'}")

        if self.log:
            self.log.alert("ATTACK", "DHCP_STARV_END",
                           f"DHCP starvation complete: {obtained} leases, {blocked} blocked")
        return result
