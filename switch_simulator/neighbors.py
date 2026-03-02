"""CDP / LLDP neighbour simulation."""

from switch_simulator.utils import format_mac, random_mac


class CDPNeighbor:
    __slots__ = ("device_id", "local_intf", "holdtime", "capability",
                 "platform", "remote_intf", "ip_address", "mac")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s, ""))
        if not self.holdtime:
            self.holdtime = 180
        if not self.mac:
            self.mac = random_mac("00:cc:dd")


class NeighborManager:
    """CDP and LLDP neighbour table."""

    def __init__(self, switch, log_engine=None):
        self.switch = switch
        self.log = log_engine
        self.cdp_enabled = True
        self.lldp_enabled = True
        self._cdp_neighbors: dict[str, CDPNeighbor] = {}   # port_name -> neighbor
        self._lldp_neighbors: dict[str, dict] = {}

    def add_cdp_neighbor(self, port_name: str, **kw):
        n = CDPNeighbor(local_intf=port_name, **kw)
        self._cdp_neighbors[port_name] = n
        port = self.switch.ports.get(port_name)
        if port:
            port.cdp_neighbor = {
                "device_id": n.device_id,
                "platform": n.platform,
                "remote_intf": n.remote_intf,
            }

    def add_lldp_neighbor(self, port_name: str, system_name: str,
                           port_desc: str = "", mgmt_ip: str = ""):
        self._lldp_neighbors[port_name] = {
            "system_name": system_name,
            "port_desc": port_desc,
            "mgmt_ip": mgmt_ip,
        }
        port = self.switch.ports.get(port_name)
        if port:
            port.lldp_neighbor = self._lldp_neighbors[port_name]

    def show_cdp(self) -> str:
        lines = []
        lines.append(f"Capability Codes: R - Router, T - Trans Bridge, B - Source Route Bridge")
        lines.append(f"                  S - Switch, H - Host, I - IGMP, r - Repeater, P - Phone")
        lines.append("")
        lines.append(f"{'Device ID':<22s} {'Local Intrfce':<18s} {'Holdtme':<10s} "
                      f"{'Capability':<12s} {'Platform':<16s} Port ID")
        for pname in sorted(self._cdp_neighbors):
            n = self._cdp_neighbors[pname]
            lines.append(
                f"{n.device_id:<22s} {n.local_intf:<18s} {n.holdtime:<10} "
                f"{n.capability:<12s} {n.platform:<16s} {n.remote_intf}"
            )
        if not self._cdp_neighbors:
            lines.append("% No CDP neighbors found")
        return "\n".join(lines)

    def show_lldp(self) -> str:
        lines = []
        lines.append(f"{'Chassis id':<22s} {'Local Intf':<18s} {'Hold-time':<12s} "
                      f"{'Capability':<12s} Port ID")
        for pname in sorted(self._lldp_neighbors):
            n = self._lldp_neighbors[pname]
            lines.append(
                f"{n['system_name']:<22s} {pname:<18s} {'120':<12s} "
                f"{'B,R':<12s} {n.get('port_desc', pname)}"
            )
        if not self._lldp_neighbors:
            lines.append("% No LLDP neighbors found")
        return "\n".join(lines)

    def to_dict(self):
        cdp = {}
        for pname, n in self._cdp_neighbors.items():
            cdp[pname] = {
                "device_id": n.device_id, "capability": n.capability,
                "platform": n.platform, "remote_intf": n.remote_intf,
                "ip_address": n.ip_address,
            }
        return {"cdp": cdp, "lldp": dict(self._lldp_neighbors)}

    def from_dict(self, data):
        for pname, info in data.get("cdp", {}).items():
            self.add_cdp_neighbor(pname, **info)
        for pname, info in data.get("lldp", {}).items():
            self.add_lldp_neighbor(pname, **info)
