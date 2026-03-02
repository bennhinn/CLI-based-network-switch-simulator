"""Full Cisco IOS-style CLI with all modes, tab-complete, colour, help."""

import os
import sys
import time
import threading
import shlex
import re

# readline portability
try:
    import readline
except ImportError:
    try:
        import pyreadline3 as readline      # Windows fallback
    except ImportError:
        readline = None

from switch_simulator.switch import Switch
from switch_simulator.utils import (
    Colors, green, yellow, red, cyan, bold, dim,
    ios_error, ios_incomplete, canonical_intf, short_intf,
    parse_interface_name, parse_vlan_list, format_mac, EXPLANATIONS
)
from switch_simulator.poe_manager import POE_DEVICES


# ───────────────────────────────────────────────────────────────────────────
# CLI mode constants
# ───────────────────────────────────────────────────────────────────────────
MODE_USER      = "user"
MODE_PRIV      = "priv"
MODE_CONF      = "config"
MODE_INTF      = "config-if"
MODE_VLAN      = "config-vlan"
MODE_LINE      = "config-line"


# ───────────────────────────────────────────────────────────────────────────
# Command abbreviation expander
# ───────────────────────────────────────────────────────────────────────────
_ABBREVS = {
    "sh":    "show",
    "sho":   "show",
    "conf":  "configure",
    "int":   "interface",
    "no":    "no",
    "ex":    "exit",
    "en":    "enable",
    "ena":   "enable",
    "dis":   "disable",
    "wr":    "write",
    "wri":   "write",
    "cop":   "copy",
    "rel":   "reload",
    "sw":    "switchport",
    "swi":   "switchport",
    "span":  "spanning-tree",
    "desc":  "description",
    "shut":  "shutdown",
    "po":    "power",
    "ip":    "ip",
    "clea":  "clear",
    "deb":   "debug",
    "unda":  "undebug",
    "undo":  "undebug",
    "do":    "do",
    "vl":    "vlan",
    "na":    "name",
    "sta":   "state",
    "ch":    "channel-group",
    "cha":   "channel-group",
    "chan":   "channel-group",
    "mont":  "monitor",
    "moni":  "monitor",
    "mls":   "mls",
    "dot":   "dot1x",
    "stor":  "storm-control",
    "atta":  "attack",
    "scen":  "scenario",
    "expl":  "explain",
    "bot":   "bottleneck",
    "era":   "erase",
    "ho":    "hostname",
    "hos":   "hostname",
}


def _expand(token: str) -> str:
    lo = token.lower()
    return _ABBREVS.get(lo, token)


def _expand_tokens(tokens: list) -> list:
    return [_expand(t) for t in tokens]

def _invalid_input(raw: str, bad_token: str = None) -> str:
    if not bad_token:
        return ios_error(raw)
    try:
        pos = raw.lower().index(bad_token.lower())
    except ValueError:
        pos = 0
    return ios_error(raw, pos)


# ───────────────────────────────────────────────────────────────────────────
# Context-sensitive help database (simplified — keyed by mode + prefix)
# ───────────────────────────────────────────────────────────────────────────
_USER_CMDS = [
    ("enable",      "Enter privileged EXEC mode"),
    ("exit",        "Exit the CLI"),
    ("show",        "Show running system information"),
    ("ping",        "Send ICMP echo (simulated)"),
]

_PRIV_CMDS = [
    ("show",        "Show running system information"),
    ("configure",   "Enter configuration mode"),
    ("write",       "Write running configuration to memory"),
    ("copy",        "Copy configuration"),
    ("erase",       "Erase configuration"),
    ("reload",      "Reload the switch"),
    ("clear",       "Reset functions"),
    ("debug",       "Enable debugging"),
    ("undebug",     "Disable debugging"),
    ("disable",     "Exit privileged mode"),
    ("exit",        "Exit the CLI"),
    ("ping",        "Send ICMP echo (simulated)"),
    ("attack",      "Run attack simulations"),
    ("scenario",    "Load lab scenarios"),
    ("explain",     "Explain a command in plain English"),
    ("bottleneck",  "Show bottleneck / congestion report"),
    ("terminal",    "Set terminal parameters"),
]

_SHOW_CMDS = [
    ("running-config",    "Current operating configuration"),
    ("startup-config",    "Contents of startup configuration"),
    ("version",           "System hardware and software status"),
    ("interfaces",        "Interface status and configuration"),
    ("vlan",              "VLAN information"),
    ("mac",               "MAC address table information"),
    ("spanning-tree",     "Spanning tree topology"),
    ("port-security",     "Port security status"),
    ("power",             "Power inline status"),
    ("ip",                "IP information"),
    ("cdp",               "CDP information"),
    ("lldp",              "LLDP information"),
    ("etherchannel",      "EtherChannel information"),
    ("monitor",           "SPAN session information"),
    ("logging",           "Syslog buffer"),
    ("dhcp",              "DHCP snooping information"),
    ("errdisable",        "Err-disable recovery information"),
    ("storm-control",     "Storm control information"),
    ("clock",             "System clock"),
]

_CONF_CMDS = [
    ("interface",       "Select an interface to configure"),
    ("vlan",            "VLAN configuration"),
    ("hostname",        "Set system hostname"),
    ("enable",          "Set privileged mode secret"),
    ("security",        "Security global configuration"),
    ("spanning-tree",   "Spanning-tree configuration"),
    ("ip",              "IP configuration"),
    ("mls",             "MLS QoS configuration"),
    ("monitor",         "SPAN / monitor session"),
    ("no",              "Negate a command or set its defaults"),
    ("exit",            "Exit configuration mode"),
    ("end",             "Return to privileged EXEC mode"),
    ("do",              "Execute an EXEC command from config mode"),
]

_INTF_CMDS = [
    ("switchport",      "Set switching mode characteristics"),
    ("description",     "Interface specific description"),
    ("shutdown",        "Shutdown the selected interface"),
    ("no",              "Negate a command"),
    ("spanning-tree",   "Spanning-tree interface configuration"),
    ("storm-control",   "Storm control configuration"),
    ("channel-group",   "EtherChannel group configuration"),
    ("power",           "Power inline configuration"),
    ("dot1x",           "802.1X port configuration"),
    ("ip",              "Interface IP configuration"),
    ("mls",             "MLS QoS interface configuration"),
    ("exit",            "Exit interface configuration mode"),
    ("end",             "Return to privileged EXEC mode"),
]


# ───────────────────────────────────────────────────────────────────────────
# The CLI class
# ───────────────────────────────────────────────────────────────────────────
class CLI:
    """Full Cisco IOS-style command-line interface."""

    def __init__(self, switch: Switch = None):
        self.switch = switch or Switch()
        self.mode = MODE_USER
        self._current_intf = None             # Port object when in config-if
        self._current_vlan_id = None          # when in config-vlan
        self._should_exit = False
        self._setup_readline()

    # ==== readline / tab-complete ==========================================
    def _setup_readline(self):
        if readline is None:
            return
        readline.set_completer(self._completer)
        readline.parse_and_bind("tab: complete")
        readline.set_completer_delims(" ")

    def _completer(self, text, state):
        try:
            buf = readline.get_line_buffer().lstrip()
            tokens = buf.split()
            # Build candidates
            candidates = self._get_completions(tokens, text)
            if state < len(candidates):
                return candidates[state]
        except Exception:
            pass
        return None

    def _get_completions(self, tokens, text):
        """Return list of possible next tokens."""
        if self.mode == MODE_USER:
            cmds = _USER_CMDS
        elif self.mode == MODE_PRIV:
            cmds = _PRIV_CMDS
        elif self.mode == MODE_CONF:
            cmds = _CONF_CMDS
        elif self.mode in (MODE_INTF, MODE_LINE):
            cmds = _INTF_CMDS
        else:
            cmds = []

        # First token — command names
        if len(tokens) <= 1:
            return [c[0] + " " for c in cmds if c[0].startswith(text.lower())]

        first = _expand(tokens[0].lower())
        if first == "show" and len(tokens) <= 2:
            return [c[0] + " " for c in _SHOW_CMDS if c[0].startswith(text.lower())]

        # Interface name completion
        if first in ("interface", "show") or (len(tokens) >= 2 and tokens[-2].lower() in ("interface",)):
            return [p.name + " " for p in self.switch.ports.values()
                     if p.name.lower().startswith(text.lower())]

        return []

    # ==== prompt ===========================================================
    @property
    def prompt(self) -> str:
        h = self.switch.hostname
        if self.mode == MODE_USER:
            return f"{h}>"
        if self.mode == MODE_PRIV:
            return f"{h}#"
        if self.mode == MODE_CONF:
            return f"{h}(config)#"
        if self.mode == MODE_INTF:
            iname = short_intf(self._current_intf.name) if self._current_intf else "?"
            return f"{h}(config-if:{iname})#"
        if self.mode == MODE_VLAN:
            return f"{h}(config-vlan)#"
        if self.mode == MODE_LINE:
            return f"{h}(config-line)#"
        return f"{h}>"

    # ==== main loop ========================================================
    def run(self):
        """Entry point — blocking REPL."""
        self.switch.start()
        print(bold(f"\n{self.switch.hostname} Switch Simulator v1.0"))
        print(f"Type {cyan('?')} for help, {cyan('explain <command>')} for explanations.\n")
        while not self._should_exit:
            try:
                self.switch.log_engine._mute_console = False
                line = input(self.prompt + " ")
                self.switch.log_engine._mute_console = True
                self._process_line(line)
            except (EOFError, KeyboardInterrupt):
                print()
                self._should_exit = True
        self.switch.stop()
        print("Switch halted.")

    # ==== input processing =================================================
    def _process_line(self, line: str):
        line = line.strip()
        if not line:
            return
        # Context help
        if line.endswith("?"):
            self._show_help(line[:-1].strip())
            return
        tokens = line.split()
        tokens = _expand_tokens(tokens)
        self._dispatch(tokens, line)

    def _dispatch(self, tokens: list, raw: str):
        """Route tokens to the handler for the current mode."""
        if not tokens:
            return
        cmd = tokens[0].lower()

        # Mark config dirty on likely mutating commands
        if self.mode in (MODE_CONF, MODE_INTF, MODE_VLAN):
            if cmd not in ("show", "do", "exit", "end", "?", "help"):
                self.switch._config_dirty = True
        elif self.mode == MODE_PRIV:
            if cmd in ("configure", "copy", "erase", "reload", "scenario"):
                self.switch._config_dirty = True

        # ── "do" in config modes ───────────────────────────────────────────
        if cmd == "do" and self.mode in (MODE_CONF, MODE_INTF, MODE_VLAN):
            saved = self.mode
            saved_intf = self._current_intf
            self.mode = MODE_PRIV
            self._dispatch(tokens[1:], " ".join(tokens[1:]))
            self.mode = saved
            self._current_intf = saved_intf
            return

        # ── mode dispatch ──────────────────────────────────────────────────
        if self.mode == MODE_USER:
            self._handle_user(tokens, raw)
        elif self.mode == MODE_PRIV:
            self._handle_priv(tokens, raw)
        elif self.mode == MODE_CONF:
            self._handle_config(tokens, raw)
        elif self.mode == MODE_INTF:
            self._handle_interface(tokens, raw)
        elif self.mode == MODE_VLAN:
            self._handle_vlan(tokens, raw)
        else:
            print(_invalid_input(raw, cmd))

    # ──────────────────────────────────────────────────────────────────────
    # USER EXEC mode
    # ──────────────────────────────────────────────────────────────────────
    def _handle_user(self, tokens, raw):
        cmd = tokens[0].lower()
        if cmd == "enable":
            secret = None
            if len(tokens) > 1:
                secret = tokens[1]
            else:
                try:
                    secret = input("Password: ")
                except Exception:
                    secret = ""
            if secret == self.switch.enable_secret:
                self.mode = MODE_PRIV
            else:
                print("% Bad secret")
        elif cmd == "exit":
            self._should_exit = True
        elif cmd == "show":
            self._handle_show(tokens[1:], raw)
        elif cmd == "ping":
            print("Type escape sequence to abort.\n!!!!!\nSuccess rate is 100 percent (5/5)")
        else:
            print(ios_error(raw))

    # ──────────────────────────────────────────────────────────────────────
    # PRIVILEGED EXEC mode
    # ──────────────────────────────────────────────────────────────────────
    def _handle_priv(self, tokens, raw):
        cmd = tokens[0].lower()
        if cmd == "show":
            self._handle_show(tokens[1:], raw)
        elif cmd == "configure":
            if len(tokens) > 1 and tokens[1].lower().startswith("t"):
                self.mode = MODE_CONF
                print("Enter configuration commands, one per line.  End with CNTL/Z.")
            else:
                print(ios_incomplete())
        elif cmd == "write":
            if len(tokens) > 1 and tokens[1].lower().startswith("m"):
                print(self.switch.write_memory())
            elif len(tokens) > 1 and tokens[1].lower().startswith("e"):
                print(self.switch.erase_startup())
            else:
                print(self.switch.write_memory())
        elif cmd == "copy":
            self._handle_copy(tokens[1:], raw)
        elif cmd == "erase":
            if len(tokens) > 1 and "start" in tokens[1].lower():
                print(self.switch.erase_startup())
            else:
                print(ios_error(raw))
        elif cmd == "reload":
            print("Proceed with reload? [confirm]")
            print(self.switch.reload())
        elif cmd == "clear":
            self._handle_clear(tokens[1:], raw)
        elif cmd == "debug":
            self._handle_debug(tokens[1:], True)
        elif cmd == "undebug":
            self._handle_debug(tokens[1:], False)
        elif cmd == "disable":
            self.mode = MODE_USER
        elif cmd == "exit":
            self._should_exit = True
        elif cmd == "ping":
            print("Type escape sequence to abort.\n!!!!!\nSuccess rate is 100 percent (5/5)")
        elif cmd == "attack":
            self._handle_attack(tokens[1:], raw)
        elif cmd == "scenario":
            self._handle_scenario(tokens[1:], raw)
        elif cmd == "explain":
            self._handle_explain(tokens[1:], raw)
        elif cmd == "bottleneck":
            print(self.switch.traffic_engine.bottleneck_report())
        elif cmd == "terminal":
            pass  # accept silently for "terminal length 0" etc.
        else:
            print(_invalid_input(raw, cmd))

    # ──────────────────────────────────────────────────────────────────────
    # SHOW commands
    # ──────────────────────────────────────────────────────────────────────
    def _handle_show(self, tokens, raw):
        if not tokens:
            print(ios_incomplete())
            return
        sub = tokens[0].lower()

        if sub in ("run", "running-config"):
            print(self.switch.running_config())

        elif sub in ("start", "startup-config"):
            print(self.switch.startup_config())

        elif sub == "version":
            print(self.switch.show_version())

        elif sub in ("int", "interfaces"):
            self._show_interfaces(tokens[1:], raw)

        elif sub in ("top-talkers", "top"):
            print(self.switch.traffic_engine.top_talkers(limit=5))

        elif sub in ("bottleneck",):
            print(self.switch.traffic_engine.bottleneck_report())

        elif sub == "vlan":
            brief = len(tokens) > 1 and tokens[1].lower().startswith("b")
            print(self.switch.vlan_db.show_brief(self.switch.ports_by_vlan())
                  if brief else
                  self.switch.vlan_db.show_full(self.switch.ports_by_vlan()))

        elif sub in ("mac",):
            # show mac address-table
            remaining = tokens[1:]
            vlan_f = None
            port_f = None
            for i, t in enumerate(remaining):
                if t.lower() == "vlan" and i + 1 < len(remaining):
                    try: vlan_f = int(remaining[i + 1])
                    except: pass
                elif t.lower() == "interface" and i + 1 < len(remaining):
                    port_f = canonical_intf(remaining[i + 1])
            print(self.switch.mac_table.show(vlan_filter=vlan_f, port_filter=port_f))

        elif sub in ("spanning-tree", "span"):
            vf = None
            if len(tokens) > 1 and tokens[1].lower().startswith("vlan"):
                if len(tokens) > 2:
                    try: vf = int(tokens[2])
                    except: pass
            print(self.switch.stp_engine.show(vlan_filter=vf))

        elif sub in ("port-security",):
            if len(tokens) > 1 and tokens[1].lower().startswith("int"):
                if len(tokens) > 2:
                    p = self.switch.get_port(tokens[2])
                    if p:
                        print(self.switch.security_engine.show_port_security(p))
                    else:
                        print(f"% Invalid interface {tokens[2]}")
                else:
                    print(ios_incomplete())
            else:
                print(self.switch.security_engine.show_port_security())

        elif sub == "power":
            if len(tokens) > 1 and tokens[1].lower() == "inline":
                if len(tokens) > 2:
                    if tokens[2].lower() == "detail" and len(tokens) > 3:
                        p = self.switch.get_port(tokens[3])
                        if p:
                            print(self.switch.poe_manager.show_power_inline_detail(p))
                        else:
                            print(f"% Invalid interface {tokens[3]}")
                    else:
                        p = self.switch.get_port(tokens[2])
                        if p:
                            print(self.switch.poe_manager.show_power_inline_detail(p))
                        else:
                            print(self.switch.poe_manager.show_power_inline())
                else:
                    print(self.switch.poe_manager.show_power_inline())
            else:
                print(self.switch.poe_manager.show_power_inline())

        elif sub == "ip":
            if len(tokens) > 1:
                sub2 = tokens[1].lower()
                if sub2.startswith("int"):
                    print(self.switch.show_ip_interface_brief())
                elif sub2 == "arp":
                    print(self.switch.arp_table.show())
                else:
                    print(ios_error(raw))
            else:
                print(ios_incomplete())

        elif sub == "cdp":
            print(self.switch.neighbor_mgr.show_cdp())

        elif sub == "lldp":
            print(self.switch.neighbor_mgr.show_lldp())

        elif sub in ("etherchannel",):
            if len(tokens) > 1 and tokens[1].lower().startswith("s"):
                print(self.switch.port_channel_mgr.show_summary())
            elif len(tokens) > 1 and tokens[1].lower().startswith("d"):
                gid = int(tokens[2]) if len(tokens) > 2 else 1
                print(self.switch.port_channel_mgr.show_detail(gid))
            else:
                print(self.switch.port_channel_mgr.show_summary())

        elif sub in ("monitor",):
            if len(tokens) > 1 and tokens[1].lower() == "session":
                print(self.switch.span_manager.show_all())
            else:
                print(self.switch.span_manager.show_all())

        elif sub in ("logging", "log"):
            tail = 50
            if len(tokens) > 1:
                try: tail = int(tokens[1])
                except: pass
            print(self.switch.log_engine.show(tail))

        elif sub == "security":
            if len(tokens) > 1 and tokens[1].lower() == "log":
                print(self.switch.log_engine.show_filtered(
                    100, facilities=("SECURITY", "ATTACK", "PORTSEC", "DAI", "DHCP_SNOOP", "IPSG")
                ))
            else:
                print(ios_error(raw))

        elif sub in ("dhcp",):
            if len(tokens) > 1 and "bind" in tokens[1].lower():
                print(self.switch.security_engine.show_dhcp_snooping_binding())
            elif len(tokens) > 1 and "snoop" in tokens[1].lower():
                if len(tokens) > 2 and "bind" in tokens[2].lower():
                    print(self.switch.security_engine.show_dhcp_snooping_binding())
                else:
                    print(self.switch.security_engine.show_dhcp_snooping_binding())
            else:
                print(self.switch.security_engine.show_dhcp_snooping_binding())

        elif sub in ("errdisable",):
            print(self.switch.security_engine.show_errdisable_recovery())

        elif sub in ("storm-control",):
            print(self.switch.security_engine.show_storm_control())

        elif sub == "clock":
            from datetime import datetime
            print(datetime.now().strftime("%H:%M:%S.%f")[:-3] + " UTC " +
                  datetime.now().strftime("%a %b %d %Y"))

        else:
            print(_invalid_input(raw, sub))

    def _show_interfaces(self, tokens, raw):
        if not tokens:
            # show all
            for pname in sorted(self.switch.ports):
                print(self.switch.ports[pname].show_interface())
                print()
            return
        sub = tokens[0].lower()
        if sub in ("status",):
            print(self.switch.show_interfaces_status())
        elif sub in ("trunk",):
            print(self.switch.show_interfaces_trunk())
        elif len(tokens) >= 2 and tokens[1].lower() == "counters":
            p = self.switch.get_port(tokens[0])
            if p:
                print(
                    f"Interface {p.name} counters:\n"
                    f"  RX packets: {p.stats.rx_packets}\n"
                    f"  RX bytes:   {p.stats.rx_bytes}\n"
                    f"  RX errors:  {p.stats.rx_errors}\n"
                    f"  TX packets: {p.stats.tx_packets}\n"
                    f"  TX bytes:   {p.stats.tx_bytes}\n"
                    f"  TX errors:  {p.stats.tx_errors}"
                )
            else:
                print(f"% Invalid input for interface: {' '.join(tokens)}")
        else:
            # specific interface
            p = self.switch.get_port(tokens[0] if len(tokens) == 1 else tokens[0] + tokens[1])
            if not p and len(tokens) >= 2:
                p = self.switch.get_port(tokens[0] + tokens[1])
            if p:
                print(p.show_interface())
            else:
                print(f"% Invalid input for interface: {' '.join(tokens)}")

    # ──────────────────────────────────────────────────────────────────────
    # GLOBAL CONFIGURATION mode
    # ──────────────────────────────────────────────────────────────────────
    def _handle_config(self, tokens, raw):
        cmd = tokens[0].lower()

        if cmd == "exit" or cmd == "end":
            self.mode = MODE_PRIV
            return

        if cmd == "interface":
            if len(tokens) < 2:
                print(ios_incomplete())
                return
            name_str = " ".join(tokens[1:])
            p = self.switch.get_port(name_str)
            if p:
                self.mode = MODE_INTF
                self._current_intf = p
            else:
                print(f"% Invalid interface {name_str}")
            return

        if cmd == "vlan":
            if len(tokens) < 2:
                print(ios_incomplete())
                return
            try:
                vid = int(tokens[1])
            except ValueError:
                print("% Invalid VLAN ID.")
                return
            err = self.switch.vlan_db.create(vid)
            if err:
                print(err)
            else:
                self._current_vlan_id = vid
                self.mode = MODE_VLAN
            return

        if cmd == "no":
            self._handle_no_config(tokens[1:], raw)
            return

        if cmd == "hostname":
            if len(tokens) < 2:
                print(ios_incomplete())
                return
            self.switch.hostname = tokens[1]
            self.switch.log_engine.hostname = tokens[1]
            return

        if cmd == "enable":
            if len(tokens) > 2 and tokens[1].lower() == "secret":
                self.switch.enable_secret = tokens[2]
                return
            print(ios_incomplete())
            return

        if cmd == "security":
            self._config_security(tokens[1:], raw)
            return

        if cmd == "spanning-tree":
            self._config_stp(tokens[1:], raw)
            return

        if cmd == "ip":
            self._config_ip_global(tokens[1:], raw)
            return

        if cmd == "mls":
            # mls qos — just accept
            return

        if cmd == "monitor":
            self._config_monitor(tokens[1:], raw)
            return

        if cmd == "errdisable":
            self._config_errdisable(tokens[1:], raw)
            return

        print(ios_error(raw))

    def _handle_no_config(self, tokens, raw):
        if not tokens:
            return
        cmd = _expand(tokens[0]).lower()
        if cmd == "vlan":
            if len(tokens) < 2:
                return
            try:
                vid = int(tokens[1])
            except ValueError:
                return
            err = self.switch.vlan_db.delete(vid)
            if err:
                print(err)
            return
        if cmd == "ip":
            if len(tokens) > 1 and "dhcp" in tokens[1].lower():
                self.switch.security_engine.dhcp_snooping_enabled = False
            elif len(tokens) > 1 and "arp" in tokens[1].lower():
                self.switch.security_engine.dai_enabled = False
            elif len(tokens) > 1 and "default" in tokens[1].lower():
                self.switch.mgmt_gateway = ""
            return
        if cmd == "monitor":
            if len(tokens) > 1 and tokens[1].lower() == "session":
                if len(tokens) > 2:
                    try:
                        sid = int(tokens[2])
                        print(self.switch.span_manager.remove_session(sid))
                    except ValueError:
                        pass
            return

    def _config_stp(self, tokens, raw):
        if not tokens:
            return
        sub = tokens[0].lower()
        if sub == "mode":
            if len(tokens) > 1:
                self.switch.stp_engine.mode = tokens[1].lower()
        elif sub == "vlan":
            # spanning-tree vlan X priority Y
            if len(tokens) >= 4 and tokens[2].lower() == "priority":
                try:
                    self.switch.stp_engine.bridge_priority = int(tokens[3])
                except ValueError:
                    print("% Invalid priority value.")

    def _config_ip_global(self, tokens, raw):
        if not tokens:
            return
        sub = tokens[0].lower()
        if sub == "dhcp":
            if len(tokens) > 1 and "snoop" in tokens[1].lower():
                if len(tokens) > 2 and tokens[2].lower() == "vlan":
                    if len(tokens) > 3:
                        try:
                            vid = int(tokens[3])
                            self.switch.security_engine.dhcp_snooping_vlans.add(vid)
                        except ValueError:
                            pass
                else:
                    self.switch.security_engine.dhcp_snooping_enabled = True
            return
        if sub == "arp":
            if len(tokens) > 1 and "insp" in tokens[1].lower():
                if len(tokens) > 2 and tokens[2].lower() == "vlan":
                    if len(tokens) > 3:
                        try:
                            vid = int(tokens[3])
                            self.switch.security_engine.dai_enabled = True
                            self.switch.security_engine.dai_vlans.add(vid)
                        except ValueError:
                            pass
                else:
                    self.switch.security_engine.dai_enabled = True
            return
        if sub == "default-gateway":
            if len(tokens) > 1:
                self.switch.mgmt_gateway = tokens[1]
            return

    def _config_monitor(self, tokens, raw):
        # monitor session <id> source interface <intf> [rx|tx|both]
        # monitor session <id> destination interface <intf>
        if len(tokens) < 2 or tokens[0].lower() != "session":
            print(ios_error(raw))
            return
        try:
            sid = int(tokens[1])
        except ValueError:
            print("% Invalid session ID.")
            return
        if len(tokens) < 3:
            print(ios_incomplete())
            return
        role = tokens[2].lower()
        if role == "source":
            if len(tokens) >= 5 and tokens[3].lower().startswith("int"):
                pname = canonical_intf(tokens[4])
                direction = tokens[5].lower() if len(tokens) > 5 else "both"
                err = self.switch.span_manager.set_source(sid, pname, direction)
                if err:
                    print(err)
            else:
                print(ios_incomplete())
        elif role in ("destination", "dest"):
            if len(tokens) >= 5 and tokens[3].lower().startswith("int"):
                pname = canonical_intf(tokens[4])
                err = self.switch.span_manager.set_destination(sid, pname)
                if err:
                    print(err)
            else:
                print(ios_incomplete())
        else:
            print(ios_error(raw))

    def _config_errdisable(self, tokens, raw):
        if not tokens:
            return
        if tokens[0].lower() == "recovery":
            if len(tokens) > 1 and tokens[1].lower() == "interval":
                if len(tokens) > 2:
                    try:
                        self.switch.security_engine.errdisable_recovery_interval = int(tokens[2])
                    except ValueError:
                        pass
            elif len(tokens) > 1:
                self.switch.security_engine.errdisable_recovery_enabled = True

    def _config_security(self, tokens, raw):
        if len(tokens) >= 3 and tokens[0].lower() == "mac-flood" and tokens[1].lower() == "threshold":
            try:
                value = int(tokens[2])
                if value < 1:
                    print("% Threshold must be >= 1")
                    return
                self.switch.security_engine.mac_flood_threshold = value
            except ValueError:
                print("% Invalid threshold value.")
            return
        print(ios_error(raw))

    # ──────────────────────────────────────────────────────────────────────
    # INTERFACE CONFIGURATION mode
    # ──────────────────────────────────────────────────────────────────────
    def _handle_interface(self, tokens, raw):
        if not tokens:
            return
        cmd = tokens[0].lower()
        port = self._current_intf

        # err-disabled guard
        if port.err_disabled and cmd not in ("exit", "end", "shutdown", "no"):
            print(f"% {port.name} is err-disabled ({port.err_disabled_reason}). "
                  f"Recover with 'shutdown' then 'no shutdown'.")
            return

        if cmd == "exit":
            self.mode = MODE_CONF
            self._current_intf = None
            return
        if cmd == "end":
            self.mode = MODE_PRIV
            self._current_intf = None
            return

        if cmd == "description":
            port.description = " ".join(tokens[1:])
            return

        if cmd == "shutdown":
            port.admin_up = False
            port.bring_down()
            self.switch.mac_table.remove_by_port(port.name)
            self.switch.stp_engine.process_link_change(port, False)
            self.switch.log_engine.info("LINK", "SHUTDOWN",
                                         f"{port.name} administratively shut down")
            return

        if cmd == "no":
            self._handle_no_intf(tokens[1:], raw, port)
            return

        if cmd == "switchport":
            self._config_switchport(tokens[1:], raw, port)
            return

        if cmd == "spanning-tree":
            self._config_stp_intf(tokens[1:], raw, port)
            return

        if cmd == "storm-control":
            self._config_storm(tokens[1:], raw, port)
            return

        if cmd == "channel-group":
            self._config_channel_group(tokens[1:], raw, port)
            return

        if cmd == "power":
            self._config_power(tokens[1:], raw, port)
            return

        if cmd == "dot1x":
            self._config_dot1x(tokens[1:], raw, port)
            return

        if cmd == "ip":
            self._config_ip_intf(tokens[1:], raw, port)
            return

        if cmd == "mls":
            self._config_mls_intf(tokens[1:], raw, port)
            return

        print(ios_error(raw))

    def _handle_no_intf(self, tokens, raw, port):
        if not tokens:
            return
        cmd = _expand(tokens[0]).lower()
        if cmd == "shutdown":
            port.admin_up = True
            if port.err_disabled:
                port.clear_err_disabled()
            port.bring_up()
            self.switch.stp_engine.process_link_change(port, True)
            self.switch.log_engine.info("LINK", "NO_SHUTDOWN",
                                         f"{port.name} administratively enabled")
            return
        if cmd == "switchport":
            if len(tokens) > 1 and tokens[1].lower() == "port-security":
                port.security.enabled = False
            return
        if cmd == "channel-group":
            if port.channel_group is not None:
                self.switch.port_channel_mgr.remove_member(port.channel_group, port.name)
            return
        if cmd == "power":
            if len(tokens) > 1 and tokens[1].lower() == "inline":
                port.poe_enabled = True
            return

    def _config_switchport(self, tokens, raw, port):
        if not tokens:
            return
        sub = tokens[0].lower()

        if sub == "mode":
            if not tokens[1:]:
                print(ios_incomplete())
                return
            mode = tokens[1].lower()
            if mode in ("access", "acc"):
                port.switchport_mode = "access"
            elif mode in ("trunk", "tru"):
                port.switchport_mode = "trunk"
            else:
                print(ios_error(raw))
            return

        if sub == "access":
            if len(tokens) > 2 and tokens[1].lower() == "vlan":
                try:
                    vid = int(tokens[2])
                    if not 1 <= vid <= 4094:
                        print("% VLAN ID must be between 1 and 4094.")
                        return
                    port.access_vlan = vid
                except ValueError:
                    print("% Invalid VLAN ID.")
            return

        if sub == "trunk":
            if len(tokens) < 2:
                return
            sub2 = tokens[1].lower()
            if sub2 == "native":
                if len(tokens) > 3 and tokens[2].lower() == "vlan":
                    try:
                        port.trunk_native_vlan = int(tokens[3])
                    except ValueError:
                        pass
            elif sub2 == "allowed":
                if len(tokens) > 3 and tokens[2].lower() == "vlan":
                    rest = " ".join(tokens[3:])
                    if rest.lower() == "none":
                        port.trunk_allowed_vlans = set()
                    elif rest.lower() == "all":
                        port.trunk_allowed_vlans = set(range(1, 4095))
                    elif rest.lower().startswith("add"):
                        vstr = rest.split(None, 1)[1] if " " in rest else ""
                        port.trunk_allowed_vlans |= parse_vlan_list(vstr)
                    elif rest.lower().startswith("remove"):
                        vstr = rest.split(None, 1)[1] if " " in rest else ""
                        port.trunk_allowed_vlans -= parse_vlan_list(vstr)
                    else:
                        port.trunk_allowed_vlans = parse_vlan_list(rest)
            elif sub2 == "encapsulation":
                if len(tokens) > 2:
                    port.trunk_encapsulation = tokens[2].lower()
            return

        if sub == "voice":
            if len(tokens) > 2 and tokens[1].lower() == "vlan":
                try:
                    port.voice_vlan = int(tokens[2])
                except ValueError:
                    pass
            return

        if sub == "port-security":
            if port.switchport_mode != "access":
                print("% Port-security is only supported on access ports.")
                return
            if len(tokens) == 1:
                port.security.enabled = True
                return
            sub2 = tokens[1].lower()
            if sub2 == "maximum":
                if len(tokens) > 2:
                    try:
                        max_value = int(tokens[2])
                        if max_value < 1:
                            print("% Maximum secure MAC addresses must be at least 1.")
                            return
                        port.security.maximum = max_value
                    except ValueError:
                        pass
            elif sub2 == "violation":
                if len(tokens) > 2:
                    mode = tokens[2].lower()
                    if mode in ("shutdown", "restrict", "protect"):
                        port.security.violation_mode = mode
            elif sub2 == "mac-address":
                if len(tokens) > 2:
                    if tokens[2].lower() == "sticky":
                        port.security.sticky = True
                        if len(tokens) > 3:
                            from switch_simulator.utils import parse_mac
                            m = parse_mac(tokens[3])
                            if m:
                                port.security.sticky_macs.add(m)
                    else:
                        from switch_simulator.utils import parse_mac
                        m = parse_mac(tokens[2])
                        if m:
                            port.security.sticky_macs.add(m)
            return

        print(ios_error(raw))

    def _config_stp_intf(self, tokens, raw, port):
        if not tokens:
            return
        sub = tokens[0].lower()
        if sub == "portfast":
            port.portfast = True
        elif sub in ("bpduguard",):
            if len(tokens) > 1 and tokens[1].lower() == "enable":
                port.bpdu_guard = True
            elif len(tokens) > 1 and tokens[1].lower() == "disable":
                port.bpdu_guard = False
            else:
                port.bpdu_guard = True
        elif sub == "guard":
            if len(tokens) > 1 and tokens[1].lower() == "root":
                port.root_guard = True
        elif sub == "cost":
            if len(tokens) > 1:
                try:
                    port.stp_port_cost = int(tokens[1])
                except ValueError:
                    pass
        elif sub == "port-priority":
            if len(tokens) > 1:
                try:
                    port.stp_port_priority = int(tokens[1])
                except ValueError:
                    pass

    def _config_storm(self, tokens, raw, port):
        if len(tokens) < 2:
            return
        ftype = tokens[0].lower()
        sub = tokens[1].lower()
        if sub == "level":
            try:
                level = float(tokens[2]) if len(tokens) > 2 else 80.0
            except ValueError:
                level = 80.0
            if ftype == "broadcast":
                port.storm_control.broadcast_level = level
            elif ftype == "multicast":
                port.storm_control.multicast_level = level
            elif ftype == "unicast":
                port.storm_control.unicast_level = level
        elif sub == "action":
            if len(tokens) > 2:
                port.storm_control.action = tokens[2].lower()

    def _config_channel_group(self, tokens, raw, port):
        if not tokens:
            return
        try:
            gid = int(tokens[0])
        except ValueError:
            print("% Invalid channel-group number.")
            return
        protocol = "on"
        if len(tokens) > 2 and tokens[1].lower() == "mode":
            protocol = tokens[2].lower()
        self.switch.port_channel_mgr.add_member(gid, port.name, protocol)

    def _config_power(self, tokens, raw, port):
        if not tokens:
            return
        if tokens[0].lower() == "inline":
            if len(tokens) > 1:
                sub = tokens[1].lower()
                if sub == "never":
                    port.poe_enabled = False
                    self.switch.poe_manager.disconnect_device(port)
                elif sub == "auto":
                    port.poe_enabled = True
                elif sub == "priority":
                    if len(tokens) > 2:
                        port.poe_priority = tokens[2].lower()
                elif sub in ("static", "consumption"):
                    if len(tokens) > 2:
                        try:
                            port.poe_max_w = float(tokens[2])
                        except ValueError:
                            pass

    def _config_dot1x(self, tokens, raw, port):
        if not tokens:
            return
        sub = tokens[0].lower()
        if sub == "port-control":
            if len(tokens) > 1 and tokens[1].lower() == "auto":
                port.dot1x.enabled = True
                port.dot1x.state = "unauthorized"
            elif len(tokens) > 1 and tokens[1].lower() == "force-authorized":
                port.dot1x.enabled = True
                port.dot1x.state = "authorized"
        elif sub == "guest-vlan":
            if len(tokens) > 1:
                try:
                    port.dot1x.guest_vlan = int(tokens[1])
                except ValueError:
                    pass
        elif sub == "reauthentication":
            port.dot1x.enabled = True
        elif sub == "timeout":
            if len(tokens) > 2 and tokens[1].lower() == "reauth-period":
                try:
                    port.dot1x.reauth_timer = int(tokens[2])
                except ValueError:
                    pass

    def _config_ip_intf(self, tokens, raw, port):
        if not tokens:
            return
        sub = tokens[0].lower()
        if sub == "dhcp":
            if len(tokens) > 1 and "snoop" in tokens[1].lower():
                if len(tokens) > 2 and tokens[2].lower() == "trust":
                    port.dhcp_snooping_trusted = True
                elif len(tokens) > 2 and tokens[2].lower() == "limit":
                    if len(tokens) > 4 and tokens[3].lower() == "rate":
                        try:
                            port.dhcp_snooping_rate_limit = int(tokens[4])
                        except ValueError:
                            pass
        elif sub == "verify":
            if len(tokens) > 1 and tokens[1].lower() == "source":
                port.ip_source_guard = True
        elif sub == "address":
            # For Vlan interface: ip address <ip> <mask>
            if len(tokens) > 2:
                self.switch.mgmt_ip = tokens[1]
                self.switch.mgmt_mask = tokens[2]

    def _config_mls_intf(self, tokens, raw, port):
        if not tokens:
            return
        if tokens[0].lower() == "qos" and len(tokens) > 1:
            if tokens[1].lower() == "trust":
                if len(tokens) > 2:
                    port.qos_trust = tokens[2].lower()
                else:
                    port.qos_trust = "cos"

    # ──────────────────────────────────────────────────────────────────────
    # VLAN CONFIGURATION mode
    # ──────────────────────────────────────────────────────────────────────
    def _handle_vlan(self, tokens, raw):
        if not tokens:
            return
        cmd = tokens[0].lower()
        if cmd == "exit":
            self.mode = MODE_CONF
            self._current_vlan_id = None
            return
        if cmd == "end":
            self.mode = MODE_PRIV
            self._current_vlan_id = None
            return
        vid = self._current_vlan_id
        if cmd == "name":
            if len(tokens) > 1:
                self.switch.vlan_db.rename(vid, " ".join(tokens[1:]))
            return
        if cmd == "state":
            if len(tokens) > 1:
                st = tokens[1].lower()
                if st == "suspend":
                    err = self.switch.vlan_db.suspend(vid)
                    if err:
                        print(err)
                elif st == "active":
                    self.switch.vlan_db.activate(vid)
            return
        if cmd == "private-vlan":
            if len(tokens) > 1:
                pvtype = tokens[1].lower()
                assoc = None
                if len(tokens) > 3 and tokens[2].lower() == "association":
                    assoc = parse_vlan_list(tokens[3])
                self.switch.vlan_db.set_private_vlan(vid, pvtype, assoc)
            return
        print(ios_error(raw))

    # ──────────────────────────────────────────────────────────────────────
    # COPY / CLEAR / DEBUG / ATTACK / SCENARIO / EXPLAIN helpers
    # ──────────────────────────────────────────────────────────────────────
    def _handle_copy(self, tokens, raw):
        if len(tokens) >= 2:
            src = tokens[0].lower()
            dst = tokens[1].lower()
            if "run" in src and "start" in dst:
                print(self.switch.write_memory())
            elif "start" in src and "run" in dst:
                if self.switch._startup_config:
                    self.switch._deserialize(self.switch._startup_config)
                    print("[OK] Startup-config applied to running-config.")
                else:
                    print("% Startup-config is empty.")
            else:
                print(ios_error(raw))
        else:
            print(ios_incomplete())

    def _handle_clear(self, tokens, raw):
        if not tokens:
            print(ios_incomplete())
            return
        sub = tokens[0].lower()
        if sub == "mac" or (sub == "mac-address-table" or sub == "mac"):
            self.switch.mac_table.clear_dynamic()
            print("Dynamic MAC entries cleared.")
        elif sub == "arp":
            self.switch.arp_table.clear()
            print("ARP table cleared.")
        elif sub == "counters":
            if len(tokens) > 1:
                p = self.switch.get_port(tokens[1])
                if p:
                    p.stats.__init__()
                    print(f"Interface counters cleared on {p.name}.")
                else:
                    print(f"% Invalid interface {tokens[1]}")
            else:
                for p in self.switch.ports.values():
                    p.stats.__init__()
                print("Interface counters cleared.")
        else:
            print(_invalid_input(raw, sub))

    def _handle_debug(self, tokens, enable: bool):
        if not tokens:
            print("% Specify debug feature: spanning-tree, port-security, arp, dhcp, mac, all")
            return
        feature = tokens[0].lower()
        if feature == "all":
            features = ["spanning-tree", "port-security", "arp", "dhcp", "mac"]
            for f in features:
                if enable:
                    self.switch.log_engine.enable_debug(f)
                else:
                    self.switch.log_engine.disable_debug(f)
        else:
            if enable:
                self.switch.log_engine.enable_debug(feature)
            else:
                self.switch.log_engine.disable_debug(feature)

    def _handle_attack(self, tokens, raw):
        if not tokens:
            print("Usage: attack simulate <mac-flood|arp-spoof|dhcp-starvation> [port <intf>]")
            return
        if tokens[0].lower() == "simulate" and len(tokens) > 1:
            atype = tokens[1].lower()
            kwargs = {}
            # Parse optional args
            i = 2
            while i < len(tokens):
                if tokens[i].lower() == "port" and i + 1 < len(tokens):
                    kwargs["port_name"] = canonical_intf(tokens[i + 1])
                    i += 2
                elif tokens[i].lower() == "count" and i + 1 < len(tokens):
                    try:
                        kwargs["count"] = int(tokens[i + 1])
                    except ValueError:
                        pass
                    i += 2
                elif tokens[i].lower() == "target" and i + 1 < len(tokens):
                    kwargs["target_ip"] = tokens[i + 1]
                    i += 2
                else:
                    # Allow shorthand: attack simulate mac-flood gi0/1
                    if "port_name" not in kwargs:
                        maybe_port = self.switch.get_port(tokens[i])
                        if maybe_port:
                            kwargs["port_name"] = maybe_port.name
                    i += 1
            result = self.switch.attack_sim.run_attack(atype, **kwargs)
            print(result)
        else:
            print("Usage: attack simulate <mac-flood|arp-spoof|dhcp-starvation>")

    def _handle_scenario(self, tokens, raw):
        if not tokens:
            print("Usage: scenario load <name>")
            print("Available scenarios: vlan_segmentation, poe_overload, mac_flood_response, "
                  "default_lab")
            return
        if tokens[0].lower() == "load" and len(tokens) > 1:
            name = tokens[1].lower()
            from switch_simulator.scenarios import load_scenario
            msg = load_scenario(self.switch, name)
            print(msg)
        elif tokens[0].lower() == "list":
            from switch_simulator.scenarios import SCENARIOS
            for s, desc in SCENARIOS.items():
                print(f"  {s:<24s} {desc}")
        else:
            print("Usage: scenario load <name>")

    def _handle_explain(self, tokens, raw):
        if not tokens:
            print("Usage: explain <command>")
            print("Example: explain show spanning-tree")
            return
        cmd_key = " ".join(tokens).lower()
        # Try exact match first, then prefix
        for key, explanation in EXPLANATIONS.items():
            if cmd_key == key.lower():
                print(f"\n{bold(key)}:")
                print(f"  {explanation}\n")
                return
        # Prefix match
        for key, explanation in EXPLANATIONS.items():
            if key.lower().startswith(cmd_key):
                print(f"\n{bold(key)}:")
                print(f"  {explanation}\n")
                return
        print(f"% No explanation found for '{' '.join(tokens)}'.")
        print("  Try: explain show running-config")

    # ──────────────────────────────────────────────────────────────────────
    # Context-sensitive help ('?')
    # ──────────────────────────────────────────────────────────────────────
    def _show_help(self, prefix: str):
        prefix_tokens = prefix.split() if prefix else []

        if self.mode == MODE_USER:
            cmds = _USER_CMDS
        elif self.mode == MODE_PRIV:
            cmds = _PRIV_CMDS
        elif self.mode == MODE_CONF:
            cmds = _CONF_CMDS
        elif self.mode in (MODE_INTF, MODE_LINE):
            cmds = _INTF_CMDS
        elif self.mode == MODE_VLAN:
            cmds = [("name", "VLAN name"), ("state", "VLAN state (active/suspend)"),
                    ("private-vlan", "Private VLAN config"), ("exit", "Exit"), ("end", "End")]
        else:
            cmds = []

        if not prefix_tokens:
            for c, desc in cmds:
                print(f"  {c:<20s} {desc}")
            return

        # token-aware help for common interface commands
        if self.mode in (MODE_INTF, MODE_LINE) and len(prefix_tokens) >= 1:
            if prefix_tokens[0].lower() == "switchport":
                if len(prefix_tokens) == 1:
                    for c, d in [
                        ("mode", "Set trunk/access mode"),
                        ("access", "Access-port options"),
                        ("trunk", "Trunk-port options"),
                        ("voice", "Voice VLAN options"),
                        ("port-security", "Port-security options"),
                    ]:
                        print(f"  {c:<20s} {d}")
                    return
                if len(prefix_tokens) >= 2 and prefix_tokens[1].lower() == "port-security":
                    for c, d in [
                        ("maximum", "Set secure MAC maximum"),
                        ("violation", "Set violation action"),
                        ("mac-address", "Configure sticky/static MACs"),
                    ]:
                        print(f"  {c:<20s} {d}")
                    return

        first = _expand(prefix_tokens[0]).lower()
        if first == "show" and len(prefix_tokens) <= 1:
            for c, desc in _SHOW_CMDS:
                print(f"  {c:<22s} {desc}")
            return

        # Generic — list matching commands
        for c, desc in cmds:
            if c.startswith(first):
                print(f"  {c:<20s} {desc}")


# ───────────────────────────────────────────────────────────────────────────
# Entry point
# ───────────────────────────────────────────────────────────────────────────
def main():
    """Launch the switch simulator CLI."""
    import argparse
    parser = argparse.ArgumentParser(description="Network Switch Simulator")
    parser.add_argument("--hostname", default="Switch", help="Switch hostname")
    parser.add_argument("--poe-budget", type=float, default=370.0,
                        help="Total PoE budget in watts")
    parser.add_argument("--load-config", type=str, default=None,
                        help="Load config from JSON/YAML file at startup")
    parser.add_argument("--scenario", type=str, default=None,
                        help="Load a named scenario at startup")
    args = parser.parse_args()

    sw = Switch(hostname=args.hostname, poe_budget=args.poe_budget)

    if args.load_config:
        msg = sw.load_config_file(args.load_config)
        print(msg)

    if args.scenario:
        from switch_simulator.scenarios import load_scenario
        msg = load_scenario(sw, args.scenario)
        print(msg)

    cli = CLI(sw)
    cli.run()


if __name__ == "__main__":
    main()
