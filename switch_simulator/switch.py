"""Switch — the top-level entity tying all subsystems together."""

import time
import json
import threading
import os

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

from switch_simulator.port import Port
from switch_simulator.vlan_db import VLANDatabase
from switch_simulator.mac_table import MACTable
from switch_simulator.arp_table import ARPTable
from switch_simulator.log_engine import LogEngine
from switch_simulator.stp_engine import STPEngine
from switch_simulator.security_engine import SecurityEngine
from switch_simulator.poe_manager import PoEManager
from switch_simulator.traffic_engine import TrafficEngine
from switch_simulator.span_manager import SPANManager
from switch_simulator.port_channel import PortChannelManager
from switch_simulator.neighbors import NeighborManager
from switch_simulator.attacks import AttackSimulator
from switch_simulator.utils import (
    format_mac, random_mac, canonical_intf, short_intf,
    format_uptime, ios_timestamp, epoch
)


class Switch:
    """Top-level network switch object.

    24 x GigabitEthernet access ports (Gi0/1 – Gi0/24)
     4 x TenGigabitEthernet uplink ports (Te0/1 – Te0/4)
    """

    MODEL = "WS-C3850-28P"
    IOS_VERSION = "16.12.4"
    SERIAL = "FCW2145L0AB"

    def __init__(self, hostname: str = "Switch", poe_budget: float = 370.0):
        self.hostname = hostname
        self.enable_secret = "cisco"
        self.base_mac = random_mac("00:ab:cd")
        self._boot_time = epoch()

        # ---- Logging (first — other engines reference it) -----------------
        self.log_engine = LogEngine(hostname)

        # ---- Data stores --------------------------------------------------
        self.vlan_db = VLANDatabase(self.log_engine)
        self.mac_table = MACTable(self.log_engine)
        self.arp_table = ARPTable(self.log_engine)

        # ---- Ports --------------------------------------------------------
        self.ports: dict[str, Port] = {}
        for i in range(1, 25):
            name = f"GigabitEthernet0/{i}"
            self.ports[name] = Port(name, speed=1_000_000_000, port_type="GE")
        for i in range(1, 5):
            name = f"TenGigabitEthernet0/{i}"
            self.ports[name] = Port(name, speed=10_000_000_000, port_type="10GE")

        # ---- Engines ------------------------------------------------------
        self.stp_engine = STPEngine(self, self.log_engine)
        self.security_engine = SecurityEngine(self, self.log_engine)
        self.poe_manager = PoEManager(self, poe_budget, self.log_engine)
        self.traffic_engine = TrafficEngine(self, self.log_engine)
        self.span_manager = SPANManager(self, self.log_engine)
        self.port_channel_mgr = PortChannelManager(self, self.log_engine)
        self.neighbor_mgr = NeighborManager(self, self.log_engine)
        self.attack_sim = AttackSimulator(self, self.log_engine)

        # ---- Management interface -----------------------------------------
        self.mgmt_vlan = 1
        self.mgmt_ip = ""
        self.mgmt_mask = ""
        self.mgmt_gateway = ""

        # ---- Config state -------------------------------------------------
        self._startup_config: dict = {}       # last saved
        self._config_dirty = False

        # ---- Background maintenance thread --------------------------------
        self._running = False
        self._maint_thread = None
        self._last_age_ts = epoch()

        # Optional inter-switch links (minimal fabric model)
        self._links: list[dict] = []

        # Log boot
        self.log_engine.info("SYS", "BOOT",
                              f"{self.hostname} booted — {self.MODEL} IOS {self.IOS_VERSION}")

    # ==== lifecycle ========================================================
    def start(self):
        """Start all background engines."""
        self._running = True
        self.stp_engine.start()
        self.security_engine.start()
        self.traffic_engine.start()
        self._maint_thread = threading.Thread(target=self._maintenance_loop,
                                               daemon=True, name="Maintenance")
        self._maint_thread.start()
        # Initial STP election
        self.stp_engine.elect(list(self.vlan_db.all_vlans().keys()),
                               list(self.ports.values()))

    def stop(self):
        self._running = False
        self.stp_engine.stop()
        self.security_engine.stop()
        self.traffic_engine.stop()

    def _maintenance_loop(self):
        while self._running:
            now = epoch()
            if now - self._last_age_ts >= 30:
                self.mac_table.age_entries()
                self.arp_table.age_entries()
                self._last_age_ts = now
            self.sync_links()
            time.sleep(5)

    # ==== uptime ===========================================================
    @property
    def uptime(self):
        return epoch() - self._boot_time

    @property
    def uptime_str(self):
        return format_uptime(self.uptime)

    # ==== port helpers =====================================================
    def get_port(self, name: str):
        """Lookup by canonical or abbreviated name."""
        if name in self.ports:
            return self.ports[name]
        canon = canonical_intf(name)
        return self.ports.get(canon)

    def ports_by_vlan(self) -> dict:
        """Return {vlan_id: [short_port_name, ...]}."""
        result: dict[int, list] = {}
        for p in self.ports.values():
            if p.switchport_mode == "access":
                result.setdefault(p.access_vlan, []).append(p.short_name)
        return result

    # ==== show version =====================================================
    def show_version(self) -> str:
        lines = []
        lines.append(f"Cisco IOS Software, {self.MODEL} Software, Version {self.IOS_VERSION}")
        lines.append(f"Copyright (c) 1986-2026 by Cisco Systems, Inc.")
        lines.append(f"ROM: Bootstrap program is IOS")
        lines.append(f"")
        lines.append(f"{self.hostname} uptime is {self.uptime_str}")
        lines.append(f"System returned to ROM by power-on")
        lines.append(f"System image file is \"flash:packages.conf\"")
        lines.append(f"")
        lines.append(f"cisco {self.MODEL} ({self.hostname}) processor with 4096K bytes of memory.")
        lines.append(f"Processor board ID {self.SERIAL}")
        lines.append(f"24 Gigabit Ethernet interfaces")
        lines.append(f"4 Ten Gigabit Ethernet interfaces")
        lines.append(f"1024K bytes of flash-simulated non-volatile configuration memory.")
        lines.append(f"Base ethernet MAC Address: {format_mac(self.base_mac)}")
        lines.append(f"Model number:   {self.MODEL}")
        lines.append(f"System serial number: {self.SERIAL}")
        return "\n".join(lines)

    # ==== show ip interface brief ==========================================
    def show_ip_interface_brief(self) -> str:
        lines = []
        lines.append(f"{'Interface':<28s} {'IP-Address':<16s} {'OK?':<5s} "
                      f"{'Method':<8s} {'Status':<16s} Protocol")
        for pname in sorted(self.ports):
            p = self.ports[pname]
            ip = "unassigned"
            status = "up" if p.admin_up else "administratively down"
            proto = p.line_protocol
            lines.append(f"{p.name:<28s} {ip:<16s} {'YES':<5s} {'unset':<8s} "
                          f"{status:<16s} {proto}")
        # Management VLAN interface
        if self.mgmt_ip:
            lines.append(f"{'Vlan' + str(self.mgmt_vlan):<28s} {self.mgmt_ip:<16s} {'YES':<5s} "
                          f"{'manual':<8s} {'up':<16s} up")
        return "\n".join(lines)

    # ==== show interfaces status ===========================================
    def show_interfaces_status(self) -> str:
        lines = []
        lines.append(f"{'Port':<18s}  {'Name':<18s}  {'Status':<12s}  {'Vlan':<8s}  "
                      f"{'Duplex':<8s}  {'Speed':<8s}  Type")
        lines.append("-" * 100)
        for pname in sorted(self.ports):
            p = self.ports[pname]
            status = p.status_str
            vlan_str = str(p.access_vlan) if p.switchport_mode == "access" else "trunk"
            if p.switchport_mode == "access":
                vlan = self.vlan_db.get(p.access_vlan)
                if vlan is None or vlan.state != "active":
                    status = "inactive"
            if p.err_disabled:
                vlan_str = "err-disabled"
            lines.append(
                f"{p.short_name:<18s}  "
                f"{p.description[:18]:<18s}  "
                f"{status:<12s}  "
                f"{vlan_str:<8s}  "
                f"{p.duplex_str:<8s}  "
                f"{p.speed_str:<8s}  "
                f"{p.media_type}"
            )
        return "\n".join(lines)

    # ==== show interfaces trunk ============================================
    def show_interfaces_trunk(self) -> str:
        lines = []
        trunks = [p for p in self.ports.values() if p.switchport_mode == "trunk"]
        if not trunks:
            return "% No trunk ports configured."
        lines.append(f"{'Port':<18s}  {'Mode':<8s}  {'Encapsulation':<16s}  "
                      f"{'Status':<12s}  Native vlan")
        lines.append("-" * 70)
        for p in sorted(trunks, key=lambda x: x.name):
            lines.append(f"{p.short_name:<18s}  {'on':<8s}  {p.trunk_encapsulation:<16s}  "
                          f"{'trunking' if p.is_up else 'not-connected':<12s}  {p.trunk_native_vlan}")
        lines.append("")
        lines.append(f"{'Port':<18s}  Vlans allowed on trunk")
        lines.append("-" * 50)
        for p in sorted(trunks, key=lambda x: x.name):
            vstr = Port._compress_vlan_set(p.trunk_allowed_vlans)
            if not p.trunk_allowed_vlans:
                vstr = f"none (native {p.trunk_native_vlan} still untagged)"
            if len(vstr) > 60:
                vstr = vstr[:57] + "..."
            lines.append(f"{p.short_name:<18s}  {vstr}")
        return "\n".join(lines)

    def connect_switch(self, peer_switch, local_port: str, peer_port: str, bidirectional: bool = True):
        lp = self.get_port(local_port)
        rp = peer_switch.get_port(peer_port)
        if not lp or not rp:
            return "% Invalid link ports."
        lp.switchport_mode = "trunk"
        rp.switchport_mode = "trunk"
        lp.bring_up()
        rp.bring_up()
        self._links.append({"local": lp.name, "peer": peer_switch, "peer_port": rp.name})
        if bidirectional:
            peer_switch._links.append({"local": rp.name, "peer": self, "peer_port": lp.name})
        self.log_engine.notice("LINK", "SWITCH_LINK",
                               f"Linked {self.hostname}:{lp.name} <-> {peer_switch.hostname}:{rp.name}")
        return "[OK] Inter-switch link established."

    @staticmethod
    def _vlan_passes_trunk(port: Port, vlan_id: int) -> bool:
        if port.switchport_mode != "trunk":
            return False
        return vlan_id in port.trunk_allowed_vlans or vlan_id == port.trunk_native_vlan

    def sync_links(self):
        for link in list(self._links):
            local_port = self.ports.get(link["local"])
            peer_switch = link.get("peer")
            peer_port = peer_switch.ports.get(link["peer_port"]) if peer_switch else None
            if not local_port or not peer_port:
                continue
            if not local_port.is_up or not peer_port.is_up:
                continue

            # VLAN propagation
            for vid, vlan in self.vlan_db.all_vlans().items():
                if vid in (1, 1002, 1003, 1004, 1005):
                    continue
                if not self._vlan_passes_trunk(local_port, vid):
                    continue
                peer_switch.vlan_db.create(vid, vlan.name)
                peer_vlan = peer_switch.vlan_db.get(vid)
                if peer_vlan:
                    peer_vlan.state = vlan.state

            # Minimal remote-MAC learning propagation
            for entry in self.mac_table.entries():
                if entry.port == local_port.name:
                    continue
                if not self._vlan_passes_trunk(local_port, entry.vlan):
                    continue
                if not self._vlan_passes_trunk(peer_port, entry.vlan):
                    continue
                peer_switch.mac_table.learn(entry.mac, entry.vlan, peer_port.name, "dynamic")

    # ==== running / startup config =========================================
    def running_config(self) -> str:
        lines = []
        lines.append("Building configuration...")
        lines.append("")
        lines.append("Current configuration : dynamic")
        if self._config_dirty:
            lines.append("! NOTE: Unsaved changes present")
        lines.append("!")
        lines.append(f"version {self.IOS_VERSION}")
        lines.append("!")
        lines.append(f"hostname {self.hostname}")
        lines.append("!")
        lines.append(f"spanning-tree mode {self.stp_engine.mode}")
        lines.append(f"spanning-tree extend system-id")
        if self.stp_engine.bridge_priority != 32768:
            lines.append(f"spanning-tree vlan 1-4094 priority {self.stp_engine.bridge_priority}")
        lines.append("!")

        # VLANs
        for vid, v in sorted(self.vlan_db.all_vlans().items()):
            if vid in (1, 1002, 1003, 1004, 1005):
                continue
            lines.append(f"vlan {vid}")
            lines.append(f" name {v.name}")
            if v.state != "active":
                lines.append(f" state {v.state}")
            lines.append("!")

        # DHCP snooping
        if self.security_engine.dhcp_snooping_enabled:
            lines.append("ip dhcp snooping")
            for v in sorted(self.security_engine.dhcp_snooping_vlans):
                lines.append(f"ip dhcp snooping vlan {v}")
            lines.append("!")

        # DAI
        if self.security_engine.dai_enabled:
            for v in sorted(self.security_engine.dai_vlans):
                lines.append(f"ip arp inspection vlan {v}")
            lines.append("!")

        # QoS
        lines.append("mls qos")
        lines.append("!")

        # Interfaces
        for pname in sorted(self.ports):
            p = self.ports[pname]
            for line in p.to_config_lines():
                lines.append(line)

        # Management
        if self.mgmt_ip:
            lines.append(f"interface Vlan{self.mgmt_vlan}")
            lines.append(f" ip address {self.mgmt_ip} {self.mgmt_mask}")
            lines.append(" no shutdown")
            lines.append("!")
            if self.mgmt_gateway:
                lines.append(f"ip default-gateway {self.mgmt_gateway}")
                lines.append("!")

        lines.append("!")
        lines.append("end")
        return "\n".join(lines)

    def startup_config(self) -> str:
        if self._startup_config:
            return self._startup_config.get("_raw_config", "% Startup config present (binary).")
        return "% Startup-config is not present."

    def write_memory(self) -> str:
        cfg = self._serialize()
        cfg["_raw_config"] = self.running_config()
        self._startup_config = cfg
        self._config_dirty = False
        self.log_engine.info("SYS", "CONFIG_SAVED", "Running-config saved to startup-config")
        return "[OK]"

    def erase_startup(self) -> str:
        self._startup_config = {}
        self.log_engine.info("SYS", "CONFIG_ERASE", "Startup-config erased")
        return "[OK] Startup-config erased."

    def reload(self) -> str:
        if self._startup_config:
            self._deserialize(self._startup_config)
        else:
            fresh = Switch(hostname="Switch", poe_budget=self.poe_manager.total_budget)
            self._deserialize(fresh._serialize())
            self.hostname = fresh.hostname
            self.enable_secret = fresh.enable_secret
            self.log_engine.hostname = self.hostname
        self._boot_time = epoch()
        self._config_dirty = False
        for p in self.ports.values():
            p.stats.__init__()
        self.log_engine.info("SYS", "RELOAD", "System reloaded")
        return "System Bootstrap, Version 16.12.4"

    # ==== save / load JSON/YAML ============================================
    def save_config_file(self, path: str) -> str:
        data = self._serialize()
        data["_raw_config"] = self.running_config()
        try:
            if path.endswith((".yml", ".yaml")) and _HAS_YAML:
                with open(path, "w") as f:
                    yaml.dump(data, f, default_flow_style=False)
            else:
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
            return f"Configuration saved to {path}"
        except Exception as e:
            return f"% Error saving config: {e}"

    def load_config_file(self, path: str) -> str:
        try:
            with open(path, "r") as f:
                if path.endswith((".yml", ".yaml")) and _HAS_YAML:
                    data = yaml.safe_load(f)
                else:
                    data = json.load(f)
            self._deserialize(data)
            return f"Configuration loaded from {path}"
        except Exception as e:
            return f"% Error loading config: {e}"

    # ==== serialization ====================================================
    def _serialize(self) -> dict:
        return {
            "hostname": self.hostname,
            "enable_secret": self.enable_secret,
            "base_mac": self.base_mac,
            "mgmt_vlan": self.mgmt_vlan,
            "mgmt_ip": self.mgmt_ip,
            "mgmt_mask": self.mgmt_mask,
            "mgmt_gateway": self.mgmt_gateway,
            "vlans": self.vlan_db.to_dict(),
            "mac_table": self.mac_table.to_dict(),
            "arp_table": self.arp_table.to_dict(),
            "stp": self.stp_engine.to_dict(),
            "security": self.security_engine.to_dict(),
            "poe": self.poe_manager.to_dict(),
            "traffic": self.traffic_engine.to_dict(),
            "span": self.span_manager.to_dict(),
            "port_channels": self.port_channel_mgr.to_dict(),
            "neighbors": self.neighbor_mgr.to_dict(),
            "ports": {pname: p.to_dict() for pname, p in self.ports.items()},
        }

    def _deserialize(self, data: dict):
        self.hostname = data.get("hostname", self.hostname)
        self.enable_secret = data.get("enable_secret", self.enable_secret)
        self.log_engine.hostname = self.hostname
        self.base_mac = data.get("base_mac", self.base_mac)
        self.mgmt_vlan = data.get("mgmt_vlan", 1)
        self.mgmt_ip = data.get("mgmt_ip", "")
        self.mgmt_mask = data.get("mgmt_mask", "")
        self.mgmt_gateway = data.get("mgmt_gateway", "")

        if "vlans" in data:
            self.vlan_db.from_dict(data["vlans"])
        if "mac_table" in data:
            self.mac_table.from_dict(data["mac_table"])
        if "arp_table" in data:
            self.arp_table.from_dict(data["arp_table"])
        if "stp" in data:
            self.stp_engine.from_dict(data["stp"])
        if "security" in data:
            self.security_engine.from_dict(data["security"])
        if "poe" in data:
            self.poe_manager.from_dict(data["poe"])
        if "traffic" in data:
            self.traffic_engine.from_dict(data["traffic"])
        if "span" in data:
            self.span_manager.from_dict(data["span"])
        if "port_channels" in data:
            self.port_channel_mgr.from_dict(data["port_channels"])
        if "neighbors" in data:
            self.neighbor_mgr.from_dict(data["neighbors"])
        if "ports" in data:
            for pname, pdata in data["ports"].items():
                if pname in self.ports:
                    self.ports[pname].from_dict(pdata)
                    # Restore sticky MACs
                    if self.ports[pname].security.sticky:
                        for m in self.ports[pname].security.sticky_macs:
                            self.mac_table.learn(m, self.ports[pname].access_vlan,
                                                  pname, "sticky")
