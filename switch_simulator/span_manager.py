"""SPAN / RSPAN port-mirroring simulation."""


class SPANSession:
    """Single SPAN / RSPAN session."""

    def __init__(self, session_id: int):
        self.session_id = session_id
        self.session_type = "local"          # local | rspan-source | rspan-dest
        self.source_ports_rx: set = set()
        self.source_ports_tx: set = set()
        self.source_ports_both: set = set()
        self.destination_port: str = ""
        self.rspan_vlan: int = 0
        self.active = True

    def show(self) -> str:
        lines = []
        lines.append(f"Session {self.session_id}")
        lines.append(f"---------")
        lines.append(f"Type                   : {self.session_type.replace('-', ' ').title()}")
        src_all = self.source_ports_both | self.source_ports_rx | self.source_ports_tx
        if self.source_ports_both:
            lines.append(f"Source Ports            :")
            lines.append(f"    Both               : {', '.join(sorted(self.source_ports_both))}")
        if self.source_ports_rx:
            lines.append(f"    RX Only            : {', '.join(sorted(self.source_ports_rx))}")
        if self.source_ports_tx:
            lines.append(f"    TX Only            : {', '.join(sorted(self.source_ports_tx))}")
        if self.destination_port:
            lines.append(f"Destination Port       : {self.destination_port}")
        if self.rspan_vlan:
            lines.append(f"RSPAN VLAN             : {self.rspan_vlan}")
        return "\n".join(lines)


class SPANManager:
    """Manage SPAN/RSPAN sessions."""

    MAX_SESSIONS = 4

    def __init__(self, switch, log_engine=None):
        self.switch = switch
        self.log = log_engine
        self.sessions: dict[int, SPANSession] = {}

    def create_session(self, session_id: int) -> SPANSession:
        if session_id not in self.sessions:
            if len(self.sessions) >= self.MAX_SESSIONS:
                return None
            self.sessions[session_id] = SPANSession(session_id)
        return self.sessions[session_id]

    def remove_session(self, session_id: int) -> str:
        if session_id in self.sessions:
            sess = self.sessions.pop(session_id)
            # Clean port flags
            for pname in (sess.source_ports_both | sess.source_ports_rx |
                          sess.source_ports_tx | {sess.destination_port}):
                p = self.switch.ports.get(pname)
                if p:
                    p.span_source = False
                    p.span_destination = False
                    p.span_session = None
            return ""
        return f"% SPAN session {session_id} not found."

    def set_source(self, session_id: int, port_name: str, direction: str = "both") -> str:
        sess = self.create_session(session_id)
        if sess is None:
            return "% Maximum SPAN sessions reached."
        if direction == "both":
            sess.source_ports_both.add(port_name)
        elif direction == "rx":
            sess.source_ports_rx.add(port_name)
        elif direction == "tx":
            sess.source_ports_tx.add(port_name)
        p = self.switch.ports.get(port_name)
        if p:
            p.span_source = True
            p.span_session = session_id
        return ""

    def set_destination(self, session_id: int, port_name: str) -> str:
        sess = self.create_session(session_id)
        if sess is None:
            return "% Maximum SPAN sessions reached."
        sess.destination_port = port_name
        p = self.switch.ports.get(port_name)
        if p:
            p.span_destination = True
            p.span_session = session_id
        return ""

    def show_all(self) -> str:
        if not self.sessions:
            return "No SPAN sessions configured."
        lines = []
        for sid in sorted(self.sessions):
            lines.append(self.sessions[sid].show())
            lines.append("")
        return "\n".join(lines)

    def to_dict(self):
        out = {}
        for sid, s in self.sessions.items():
            out[sid] = {
                "type": s.session_type,
                "src_both": sorted(s.source_ports_both),
                "src_rx": sorted(s.source_ports_rx),
                "src_tx": sorted(s.source_ports_tx),
                "dst": s.destination_port,
                "rspan_vlan": s.rspan_vlan,
            }
        return out

    def from_dict(self, data):
        for sid_s, info in data.items():
            sid = int(sid_s)
            sess = self.create_session(sid)
            sess.session_type = info.get("type", "local")
            sess.source_ports_both = set(info.get("src_both", []))
            sess.source_ports_rx = set(info.get("src_rx", []))
            sess.source_ports_tx = set(info.get("src_tx", []))
            sess.destination_port = info.get("dst", "")
            sess.rspan_vlan = info.get("rspan_vlan", 0)
