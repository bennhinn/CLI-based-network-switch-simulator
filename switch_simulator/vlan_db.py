"""VLAN database with Cisco-style semantics."""

import threading


class VLANEntry:
    __slots__ = ("vid", "name", "state", "private_vlan_type",
                 "private_vlan_assoc", "is_default")

    def __init__(self, vid: int, name: str = "", state: str = "active"):
        self.vid = vid
        self.name = name or f"VLAN{vid:04d}"
        self.state = state                     # active | suspend | act/unsup
        self.private_vlan_type = None          # isolated | community | primary
        self.private_vlan_assoc = set()        # associated VLANs
        self.is_default = vid == 1


class VLANDatabase:
    """Full VLAN database with 1-4094 support."""

    def __init__(self, log_engine=None):
        self._vlans: dict[int, VLANEntry] = {}
        self._lock = threading.Lock()
        self.log = log_engine
        # Default VLANs per IOS
        self._create_defaults()

    def _create_defaults(self):
        defaults = {
            1: "default",
            1002: "fddi-default",
            1003: "token-ring-default",
            1004: "fddinet-default",
            1005: "trnet-default",
        }
        for vid, name in defaults.items():
            self._vlans[vid] = VLANEntry(vid, name)

    # ---- CRUD ---------------------------------------------------------------
    def create(self, vid: int, name: str = "") -> str:
        if not 1 <= vid <= 4094:
            return "% VLAN ID must be between 1 and 4094."
        if vid in (1, 1002, 1003, 1004, 1005):
            if vid in self._vlans:
                return ""            # silently accept re-entry of defaults
            return f"% Default VLAN {vid} may not be deleted/changed."
        with self._lock:
            if vid in self._vlans:
                if name:
                    self._vlans[vid].name = name
                return ""
            self._vlans[vid] = VLANEntry(vid, name)
        if self.log:
            self.log.info("VLAN", "VLAN_CREATE", f"VLAN {vid} created{' name ' + name if name else ''}")
        return ""

    def delete(self, vid: int) -> str:
        if vid == 1:
            return "% Default VLAN 1 may not be deleted."
        if vid in (1002, 1003, 1004, 1005):
            return f"% Default VLAN {vid} may not be deleted."
        with self._lock:
            if vid not in self._vlans:
                return f"% VLAN {vid} not found in current database."
            del self._vlans[vid]
        if self.log:
            self.log.info("VLAN", "VLAN_DELETE", f"VLAN {vid} deleted")
        return ""

    def rename(self, vid: int, name: str) -> str:
        with self._lock:
            if vid not in self._vlans:
                return f"% VLAN {vid} not found."
            self._vlans[vid].name = name
        return ""

    def suspend(self, vid: int) -> str:
        if vid == 1:
            return "% Cannot suspend default VLAN 1."
        with self._lock:
            if vid not in self._vlans:
                return f"% VLAN {vid} not found."
            self._vlans[vid].state = "suspend"
        return ""

    def activate(self, vid: int) -> str:
        with self._lock:
            if vid not in self._vlans:
                return f"% VLAN {vid} not found."
            self._vlans[vid].state = "active"
        return ""

    def exists(self, vid: int) -> bool:
        return vid in self._vlans

    def get(self, vid: int):
        return self._vlans.get(vid)

    def all_vlans(self):
        return dict(self._vlans)

    def set_private_vlan(self, vid: int, pvlan_type: str, assoc=None) -> str:
        with self._lock:
            if vid not in self._vlans:
                return f"% VLAN {vid} not found."
            self._vlans[vid].private_vlan_type = pvlan_type
            if assoc is not None:
                self._vlans[vid].private_vlan_assoc = set(assoc)
        return ""

    # ---- show vlan ---------------------------------------------------------
    def show_brief(self, ports_by_vlan: dict = None) -> str:
        lines = []
        lines.append("")
        lines.append(f"{'VLAN':4s}  {'Name':<32s}  {'Status':<10s}  Ports")
        lines.append("-" * 4 + "  " + "-" * 32 + "  " + "-" * 10 + "  " + "-" * 30)
        for vid in sorted(self._vlans):
            v = self._vlans[vid]
            port_list = ""
            if ports_by_vlan and vid in ports_by_vlan:
                port_list = ", ".join(ports_by_vlan[vid])
            lines.append(f"{vid:<4d}  {v.name:<32s}  {v.state:<10s}  {port_list}")
        lines.append("")
        return "\n".join(lines)

    def show_full(self, ports_by_vlan: dict = None) -> str:
        return self.show_brief(ports_by_vlan)

    # ---- serialization -----------------------------------------------------
    def to_dict(self):
        return {vid: {"name": v.name, "state": v.state,
                       "pvlan_type": v.private_vlan_type,
                       "pvlan_assoc": list(v.private_vlan_assoc)}
                for vid, v in self._vlans.items()}

    def from_dict(self, data: dict):
        with self._lock:
            self._vlans.clear()
            self._create_defaults()
            for vid_s, info in data.items():
                vid = int(vid_s)
                if vid not in self._vlans:
                    self._vlans[vid] = VLANEntry(vid, info.get("name", ""))
                self._vlans[vid].name = info.get("name", self._vlans[vid].name)
                self._vlans[vid].state = info.get("state", "active")
                self._vlans[vid].private_vlan_type = info.get("pvlan_type")
                self._vlans[vid].private_vlan_assoc = set(info.get("pvlan_assoc", []))
