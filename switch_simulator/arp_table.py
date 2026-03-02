"""ARP table simulation."""

import threading
import time
from switch_simulator.utils import format_mac


class ARPEntry:
    __slots__ = ("ip", "mac", "vlan", "port", "entry_type", "age")

    def __init__(self, ip: str, mac: str, vlan: int = 1, port: str = "",
                 entry_type: str = "dynamic"):
        self.ip = ip
        self.mac = mac
        self.vlan = vlan
        self.port = port
        self.entry_type = entry_type      # dynamic | static
        self.age = 0                      # minutes


class ARPTable:
    """ARP table with aging."""

    TIMEOUT = 240   # minutes

    def __init__(self, log_engine=None):
        self._table: dict[str, ARPEntry] = {}   # ip -> entry
        self._lock = threading.Lock()
        self.log = log_engine

    def add(self, ip: str, mac: str, vlan: int = 1, port: str = "",
            entry_type: str = "dynamic"):
        with self._lock:
            self._table[ip] = ARPEntry(ip, mac, vlan, port, entry_type)
        if self.log:
            self.log.debug("arp", f"ARP entry added: {ip} -> {format_mac(mac)}")

    def lookup(self, ip: str):
        return self._table.get(ip)

    def remove(self, ip: str):
        with self._lock:
            self._table.pop(ip, None)

    def clear(self):
        with self._lock:
            self._table.clear()

    def age_entries(self):
        with self._lock:
            to_del = []
            for ip, entry in self._table.items():
                if entry.entry_type == "dynamic":
                    entry.age += 1
                    if entry.age > self.TIMEOUT:
                        to_del.append(ip)
            for ip in to_del:
                del self._table[ip]

    def show(self) -> str:
        lines = []
        lines.append(f"{'Protocol':<10s} {'Address':<16s} {'Age (min)':<12s} "
                      f"{'Hardware Addr':<18s} {'Type':<8s} Interface")
        for ip in sorted(self._table):
            e = self._table[ip]
            age_str = str(e.age) if e.entry_type == "dynamic" else "-"
            lines.append(
                f"{'Internet':<10s} {e.ip:<16s} {age_str:<12s} "
                f"{format_mac(e.mac):<18s} {'ARPA':<8s} {e.port}"
            )
        return "\n".join(lines)

    def to_dict(self):
        return [{"ip": e.ip, "mac": e.mac, "vlan": e.vlan, "port": e.port,
                  "type": e.entry_type}
                for e in self._table.values() if e.entry_type == "static"]

    def from_dict(self, data):
        for d in data:
            self.add(d["ip"], d["mac"], d.get("vlan", 1), d.get("port", ""),
                     d.get("type", "static"))
