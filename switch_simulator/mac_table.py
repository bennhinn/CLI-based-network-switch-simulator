"""MAC address table with aging, static entries, and eviction."""

import threading
import time

from switch_simulator.utils import format_mac


class MACEntry:
    __slots__ = ("mac", "vlan", "port", "entry_type", "last_seen")

    def __init__(self, mac: str, vlan: int, port: str,
                 entry_type: str = "dynamic"):
        self.mac = mac                        # normalised 12-char hex
        self.vlan = vlan
        self.port = port                      # canonical interface name
        self.entry_type = entry_type          # dynamic | static | sticky
        self.last_seen = time.time()


class MACTable:
    """Layer-2 forwarding table with aging and eviction."""

    MAX_ENTRIES = 1024
    DEFAULT_AGING = 300  # seconds

    def __init__(self, log_engine=None):
        self._table: dict[tuple, MACEntry] = {}   # (mac, vlan) -> entry
        self._lock = threading.Lock()
        self.aging_time = self.DEFAULT_AGING
        self.log = log_engine

    # ---- learn / lookup ----------------------------------------------------
    def learn(self, mac: str, vlan: int, port: str, entry_type: str = "dynamic") -> bool:
        """Learn a MAC. Returns True if new, False if update."""
        key = (mac, vlan)
        with self._lock:
            if key in self._table:
                e = self._table[key]
                changed = e.port != port
                e.port = port
                e.last_seen = time.time()
                if e.entry_type == "dynamic":
                    e.entry_type = entry_type
                return changed
            # evict oldest if full
            if len(self._table) >= self.MAX_ENTRIES:
                self._evict_oldest()
            self._table[key] = MACEntry(mac, vlan, port, entry_type)
        if self.log:
            self.log.debug("mac", f"Learned {format_mac(mac)} on VLAN {vlan} port {port}")
        return True

    def lookup(self, mac: str, vlan: int):
        """Return the port for a given MAC+VLAN or None."""
        e = self._table.get((mac, vlan))
        if e:
            e.last_seen = time.time()
            return e.port
        return None

    def remove_by_port(self, port: str):
        """Remove all dynamic entries for a port (link down)."""
        with self._lock:
            to_del = [k for k, v in self._table.items()
                       if v.port == port and v.entry_type == "dynamic"]
            for k in to_del:
                del self._table[k]

    def remove_by_vlan(self, vlan: int):
        with self._lock:
            to_del = [k for k, v in self._table.items() if v.vlan == vlan]
            for k in to_del:
                del self._table[k]

    def add_static(self, mac: str, vlan: int, port: str):
        self.learn(mac, vlan, port, "static")

    def count(self):
        return len(self._table)

    def count_by_port(self, port: str):
        return sum(1 for v in self._table.values() if v.port == port)

    def macs_on_port(self, port: str):
        return [v for v in self._table.values() if v.port == port]

    def entries(self):
        with self._lock:
            return [v for v in self._table.values()]

    # ---- aging -------------------------------------------------------------
    def age_entries(self):
        """Remove expired dynamic entries. Call periodically."""
        now = time.time()
        with self._lock:
            to_del = [k for k, v in self._table.items()
                       if v.entry_type == "dynamic"
                       and (now - v.last_seen) > self.aging_time]
            for k in to_del:
                del self._table[k]

    def _evict_oldest(self):
        """Evict oldest dynamic entry. Must hold lock."""
        dyn = [(k, v) for k, v in self._table.items() if v.entry_type == "dynamic"]
        if not dyn:
            return
        oldest = min(dyn, key=lambda x: x[1].last_seen)
        del self._table[oldest[0]]
        if self.log:
            self.log.debug("mac", f"Evicted oldest MAC entry {format_mac(oldest[0][0])}")

    def clear_dynamic(self):
        with self._lock:
            to_del = [k for k, v in self._table.items() if v.entry_type == "dynamic"]
            for k in to_del:
                del self._table[k]

    # ---- show mac address-table --------------------------------------------
    def show(self, vlan_filter=None, port_filter=None) -> str:
        lines = []
        lines.append(f"          Mac Address Table")
        lines.append("-" * 56)
        lines.append(f"{'Vlan':>4s}    {'Mac Address':<16s}    {'Type':<10s}    Ports")
        lines.append("-" * 4 + "    " + "-" * 16 + "    " + "-" * 10 + "    " + "-" * 16)
        entries = sorted(self._table.values(), key=lambda e: (e.vlan, e.mac))
        for e in entries:
            if vlan_filter and e.vlan != vlan_filter:
                continue
            if port_filter and e.port != port_filter:
                continue
            lines.append(f"{e.vlan:>4d}    {format_mac(e.mac):<16s}    "
                         f"{e.entry_type.upper():<10s}    {e.port}")
        lines.append(f"Total Mac Addresses for this criterion: {len(entries)}")
        return "\n".join(lines)

    # ---- serialization -----------------------------------------------------
    def to_dict(self):
        return [{"mac": e.mac, "vlan": e.vlan, "port": e.port, "type": e.entry_type}
                for e in self._table.values() if e.entry_type in ("static", "sticky")]

    def from_dict(self, data: list):
        for d in data:
            self.learn(d["mac"], d["vlan"], d["port"], d.get("type", "static"))
