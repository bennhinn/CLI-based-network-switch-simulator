"""Spanning Tree Protocol engine — Rapid-PVST+ simulation."""

import threading
import time
import random
from switch_simulator.utils import format_mac


class BPDUMessage:
    """Simulated BPDU."""
    __slots__ = ("root_id", "root_cost", "bridge_id", "port_id",
                 "message_age", "max_age", "hello_time", "forward_delay",
                 "vlan", "flags")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        for s in self.__slots__:
            if not hasattr(self, s):
                setattr(self, s, 0)


class STPEngine:
    """Per-VLAN Rapid Spanning-Tree simulation."""

    def __init__(self, switch, log_engine=None):
        self.switch = switch
        self.log = log_engine
        self.mode = "rapid-pvst"
        self.bridge_priority = 32768
        self._bridge_mac = switch.base_mac if hasattr(switch, 'base_mac') else "aabbccdd0000"
        self._root_info: dict = {}           # vlan -> {root_id, root_cost, root_port}
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    @property
    def bridge_id(self):
        return f"{self.bridge_priority:05d}.{format_mac(self._bridge_mac)}"

    def root_bridge_for_vlan(self, vlan: int) -> dict:
        default = {"root_id": self.bridge_id, "root_cost": 0, "root_port": "None"}
        return self._root_info.get(vlan, default)

    # ---- election ----------------------------------------------------------
    def elect(self, vlans: list[int], ports: list):
        """Run root election for each VLAN. Simple simulation."""
        with self._lock:
            for vlan in vlans:
                # In single-switch mode we are always root
                self._root_info[vlan] = {
                    "root_id": self.bridge_id,
                    "root_cost": 0,
                    "root_port": "None",
                }
                for p in ports:
                    if not p.is_up:
                        p.stp_state = "disabled"
                        p.stp_role = "disabled"
                        continue
                    if p.portfast:
                        p.stp_state = "forwarding"
                        p.stp_role = "designated"
                        continue
                    p.stp_state = "forwarding"
                    p.stp_role = "designated"

    def process_link_change(self, port, up: bool):
        """Handle topology change notification."""
        if self.log:
            state = "UP" if up else "DOWN"
            self.log.notice("STP", "TOPOLOGY_CHANGE",
                            f"Port {port.name} link {state} — topology change notification")
        # Re-derive roles
        active_vlans = list(self._root_info.keys()) or [1]
        ports = list(self.switch.ports.values()) if hasattr(self.switch, 'ports') else []
        self.elect(active_vlans, ports)

    def process_bpdu(self, port, bpdu: BPDUMessage):
        """Process incoming BPDU on a port."""
        if port.bpdu_guard:
            port.set_err_disabled("bpdu-guard")
            if self.log:
                self.log.warn("STP", "BPDUGUARD",
                              f"BPDU guard violation on {port.name} — port err-disabled")
            return
        if port.root_guard:
            # If BPDU has superior root, block
            if self.log:
                self.log.warn("STP", "ROOTGUARD",
                              f"Root guard activated on {port.name} — superior BPDU received")
            port.stp_state = "root-inconsistent"
            return
        if self.log:
            self.log.debug("spanning-tree",
                           f"BPDU rx on {port.name}: root={bpdu.root_id} cost={bpdu.root_cost}")

    def send_bpdu(self, port, vlan: int):
        """Simulate sending a BPDU out a port."""
        bpdu = BPDUMessage(
            root_id=self.bridge_id,
            root_cost=0,
            bridge_id=self.bridge_id,
            port_id=port.stp_port_priority,
            message_age=0,
            max_age=20,
            hello_time=2,
            forward_delay=15,
            vlan=vlan,
        )
        if self.log:
            self.log.debug("spanning-tree",
                           f"BPDU tx on {port.name} vlan {vlan}")
        return bpdu

    # ---- background thread ------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="STP")
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            try:
                active_vlans = list(self._root_info.keys()) or [1]
                ports = list(self.switch.ports.values()) if hasattr(self.switch, 'ports') else []
                self.elect(active_vlans, ports)
            except Exception:
                pass
            time.sleep(2)  # hello timer

    # ---- show spanning-tree ------------------------------------------------
    def show(self, vlan_filter=None) -> str:
        lines = []
        vlans = [vlan_filter] if vlan_filter else sorted(self._root_info.keys())
        if not vlans:
            vlans = [1]
        for vlan in vlans:
            ri = self.root_bridge_for_vlan(vlan)
            lines.append(f"")
            lines.append(f"VLAN{vlan:04d}")
            lines.append(f"  Spanning tree enabled protocol {self.mode}")
            lines.append(f"  Root ID    Priority    {self.bridge_priority}")
            lines.append(f"             Address     {format_mac(self._bridge_mac)}")
            lines.append(f"             Cost        {ri['root_cost']}")
            lines.append(f"             Port        {ri['root_port']}")
            lines.append(f"             Hello Time   2 sec  Max Age 20 sec  Forward Delay 15 sec")
            lines.append(f"")
            lines.append(f"  Bridge ID  Priority    {self.bridge_priority}")
            lines.append(f"             Address     {format_mac(self._bridge_mac)}")
            lines.append(f"             Hello Time   2 sec  Max Age 20 sec  Forward Delay 15 sec")
            lines.append(f"")
            lines.append(f"{'Interface':<22s} {'Role':<12s} {'Sts':<12s} {'Cost':<6s} "
                          f"{'Prio.Nbr':<10s} Type")
            lines.append("-" * 76)
            if hasattr(self.switch, 'ports'):
                for pname in sorted(self.switch.ports):
                    p = self.switch.ports[pname]
                    if not p.is_up:
                        continue
                    if p.switchport_mode == "access" and p.access_vlan != vlan:
                        continue
                    if p.switchport_mode == "trunk" and vlan not in p.trunk_allowed_vlans:
                        continue
                    ptype = "P2p" if not p.portfast else "P2p Edge"
                    lines.append(
                        f"{p.short_name:<22s} {p.stp_role:<12s} {p.stp_state[:3].upper():<12s} "
                        f"{p.stp_cost():<6d} {p.stp_port_priority}.1{'':>6s} {ptype}"
                    )
        return "\n".join(lines)

    # ---- serialization ---------------------------------------------------
    def to_dict(self):
        return {"mode": self.mode, "priority": self.bridge_priority}

    def from_dict(self, data):
        self.mode = data.get("mode", "rapid-pvst")
        self.bridge_priority = data.get("priority", 32768)
