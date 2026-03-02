"""Port-channel / EtherChannel (LACP/PAgP) simulation."""

import threading
from switch_simulator.utils import short_intf


class PortChannel:
    """Represents a logical port-channel interface."""

    def __init__(self, group_id: int, protocol: str = "lacp"):
        self.group_id = group_id
        self.name = f"Port-channel{group_id}"
        self.protocol = protocol             # lacp | pagp | on
        self.members: list[str] = []         # list of member interface names
        self.admin_up = True
        self.min_links = 1

    @property
    def is_up(self):
        return self.admin_up and len(self.members) >= self.min_links


class PortChannelManager:
    """Manage port-channel groups."""

    def __init__(self, switch, log_engine=None):
        self.switch = switch
        self.log = log_engine
        self.channels: dict[int, PortChannel] = {}

    def add_member(self, group_id: int, port_name: str,
                   protocol: str = "lacp") -> str:
        if group_id not in self.channels:
            self.channels[group_id] = PortChannel(group_id, protocol)
        ch = self.channels[group_id]
        if port_name not in ch.members:
            ch.members.append(port_name)
        port = self.switch.ports.get(port_name)
        if port:
            port.channel_group = group_id
            port.channel_protocol = protocol
        if self.log:
            self.log.info("EC", "MEMBER_ADD",
                          f"{port_name} added to Port-channel{group_id} ({protocol})")
        return ""

    def remove_member(self, group_id: int, port_name: str) -> str:
        ch = self.channels.get(group_id)
        if not ch:
            return f"% Port-channel{group_id} not found."
        if port_name in ch.members:
            ch.members.remove(port_name)
        port = self.switch.ports.get(port_name)
        if port:
            port.channel_group = None
            port.channel_protocol = None
        if not ch.members:
            del self.channels[group_id]
        return ""

    def show_summary(self) -> str:
        lines = []
        lines.append(f"{'Group':<8s} {'Port-channel':<18s} {'Protocol':<10s} Ports")
        lines.append("-" * 60)
        for gid in sorted(self.channels):
            ch = self.channels[gid]
            status = "SU" if ch.is_up else "SD"
            members = " ".join(f"{short_intf(m)}(P)" for m in ch.members)
            lines.append(
                f"{gid:<8d} {ch.name + '(' + status + ')':<18s} {ch.protocol:<10s} {members}"
            )
        if not self.channels:
            lines.append("No port-channel groups configured.")
        return "\n".join(lines)

    def show_detail(self, group_id: int) -> str:
        ch = self.channels.get(group_id)
        if not ch:
            return f"% Port-channel{group_id} not found."
        lines = []
        lines.append(f"Port-channel{group_id}:")
        lines.append(f"  Protocol: {ch.protocol.upper()}")
        lines.append(f"  Status: {'Up' if ch.is_up else 'Down'}")
        lines.append(f"  Min-links: {ch.min_links}")
        lines.append(f"  Members ({len(ch.members)}):")
        for m in ch.members:
            port = self.switch.ports.get(m)
            state = "Active" if port and port.is_up else "Down"
            lines.append(f"    {m}: {state}")
        return "\n".join(lines)

    def to_dict(self):
        return {gid: {"protocol": ch.protocol, "members": ch.members,
                       "min_links": ch.min_links}
                for gid, ch in self.channels.items()}

    def from_dict(self, data):
        for gid_s, info in data.items():
            gid = int(gid_s)
            for member in info.get("members", []):
                self.add_member(gid, member, info.get("protocol", "lacp"))
            if gid in self.channels:
                self.channels[gid].min_links = info.get("min_links", 1)
