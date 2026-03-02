"""Syslog / event logging engine matching Cisco severity levels."""

import threading
import time
from collections import deque
from datetime import datetime
from switch_simulator.utils import Colors


# Cisco syslog severity levels
SEVERITY = {
    0: "EMERG",   1: "ALERT",  2: "CRIT",   3: "ERROR",
    4: "WARN",    5: "NOTICE", 6: "INFO",    7: "DEBUG",
}

_SEV_COLOR = {
    0: Colors.ERR,  1: Colors.ERR,  2: Colors.ERR,  3: Colors.ERR,
    4: Colors.WARN,  5: Colors.WARN,  6: Colors.OK,   7: Colors.DIM,
}


class LogEngine:
    """Thread-safe syslog buffer with Cisco-style formatting."""

    MAX_BUFFER = 4096

    def __init__(self, hostname="Switch"):
        self.hostname = hostname
        self._buffer = deque(maxlen=self.MAX_BUFFER)
        self._lock = threading.Lock()
        self._console_level = 6          # show INFO and below on console
        self._buffer_level = 7           # store everything
        self._debug_flags: set = set()   # e.g. {"spanning-tree", "port-security"}
        self._mute_console = False       # suppress during CLI input

    # ---- public API --------------------------------------------------------
    def log(self, severity: int, facility: str, mnemonic: str, message: str,
            *, echo_console: bool = True):
        ts = datetime.now().strftime("%b %d %H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}"
        entry = {
            "timestamp": ts,
            "severity": severity,
            "facility": facility,
            "mnemonic": mnemonic,
            "message": message,
        }
        with self._lock:
            self._buffer.append(entry)
        if echo_console and not self._mute_console and severity <= self._console_level:
            self._print_entry(entry)

    def debug(self, facility: str, message: str):
        if facility.lower() in self._debug_flags:
            self.log(7, facility.upper(), "DEBUG", message)

    def emerg(self, fac, mnem, msg):   self.log(0, fac, mnem, msg)
    def alert(self, fac, mnem, msg):   self.log(1, fac, mnem, msg)
    def crit(self, fac, mnem, msg):    self.log(2, fac, mnem, msg)
    def error(self, fac, mnem, msg):   self.log(3, fac, mnem, msg)
    def warn(self, fac, mnem, msg):    self.log(4, fac, mnem, msg)
    def notice(self, fac, mnem, msg):  self.log(5, fac, mnem, msg)
    def info(self, fac, mnem, msg):    self.log(6, fac, mnem, msg)

    # ---- debug toggle ------------------------------------------------------
    def enable_debug(self, feature: str):
        self._debug_flags.add(feature.lower())
        self.info("SYS", "DEBUG_ON", f"Debugging enabled for {feature}")

    def disable_debug(self, feature: str):
        self._debug_flags.discard(feature.lower())
        self.info("SYS", "DEBUG_OFF", f"Debugging disabled for {feature}")

    # ---- show logging ------------------------------------------------------
    def show(self, tail: int = 50) -> str:
        lines = []
        lines.append(f"Syslog logging enabled (buffer size {self.MAX_BUFFER})")
        lines.append(f"Console logging: level {SEVERITY.get(self._console_level, '?')} "
                      f"(severity {self._console_level})")
        lines.append(f"Buffer logging:  level {SEVERITY.get(self._buffer_level, '?')} "
                      f"(severity {self._buffer_level})")
        lines.append(f"Debug flags:     {', '.join(sorted(self._debug_flags)) or 'none'}")
        lines.append("")
        lines.append("Log Buffer:")
        lines.append("-" * 72)
        with self._lock:
            entries = list(self._buffer)[-tail:]
        for e in entries:
            lines.append(self._format_entry(e))
        return "\n".join(lines)

    def show_filtered(self, tail: int = 50, facilities: tuple = ()) -> str:
        lines = []
        lines.append(f"Syslog logging enabled (buffer size {self.MAX_BUFFER})")
        lines.append(f"Filter facilities: {', '.join(facilities) if facilities else 'none'}")
        lines.append("")
        lines.append("Log Buffer:")
        lines.append("-" * 72)
        with self._lock:
            entries = list(self._buffer)
        if facilities:
            wanted = {f.upper() for f in facilities}
            entries = [e for e in entries if e.get("facility", "").upper() in wanted]
        entries = entries[-tail:]
        for e in entries:
            lines.append(self._format_entry(e))
        return "\n".join(lines)

    # ---- internal ----------------------------------------------------------
    def _format_entry(self, e: dict) -> str:
        sev = SEVERITY.get(e["severity"], "?")
        return (f"{e['timestamp']}: %{e['facility']}-{e['severity']}-{e['mnemonic']}: "
                f"{e['message']}")

    def _print_entry(self, e: dict):
        color = _SEV_COLOR.get(e["severity"], "")
        txt = self._format_entry(e)
        print(f"\r{color}{txt}{Colors.RESET}")
