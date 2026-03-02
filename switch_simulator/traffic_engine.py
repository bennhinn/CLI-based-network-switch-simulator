"""Traffic simulation engine — background threads, congestion, storms, link flap."""

import threading
import time
import random
from switch_simulator.utils import format_bps, format_bytes, random_mac


class TrafficEngine:
    """Generates realistic background traffic on ports and detects bottlenecks."""

    def __init__(self, switch, log_engine=None):
        self.switch = switch
        self.log = log_engine
        self._running = False
        self._thread = None
        self._sim_configs: dict = {}           # port_name -> traffic profile
        self._congestion_threshold = 80.0      # percent
        self._lock = threading.Lock()

    # ---- traffic profile per port -----------------------------------------
    def set_traffic(self, port_name: str, avg_mbps: float = 100.0,
                    burst_pct: float = 20.0, broadcast_pct: float = 2.0):
        """Configure simulated traffic for a port."""
        self._sim_configs[port_name] = {
            "avg_mbps": avg_mbps,
            "burst_pct": burst_pct,
            "broadcast_pct": broadcast_pct,
        }

    def remove_traffic(self, port_name: str):
        self._sim_configs.pop(port_name, None)

    # ---- background loop --------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="TrafficEngine")
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(1.0)

    def _tick(self):
        for pname, cfg in list(self._sim_configs.items()):
            port = self.switch.ports.get(pname)
            if not port or not port.is_up:
                continue

            avg_bps = cfg["avg_mbps"] * 1_000_000
            burst = cfg["burst_pct"] / 100.0
            bc_pct = cfg["broadcast_pct"] / 100.0

            # Random jitter
            jitter = random.uniform(1.0 - burst, 1.0 + burst)
            rate = avg_bps * jitter
            bytes_per_sec = int(rate / 8)
            pkts = max(1, bytes_per_sec // 800)  # ~800B avg pkt

            # Split rx/tx roughly
            rx_bytes = int(bytes_per_sec * random.uniform(0.4, 0.6))
            tx_bytes = bytes_per_sec - rx_bytes
            rx_pkts = int(pkts * 0.5)
            tx_pkts = pkts - rx_pkts

            port.stats.rx_bytes += rx_bytes
            port.stats.tx_bytes += tx_bytes
            port.stats.rx_packets += rx_pkts
            port.stats.tx_packets += tx_pkts
            port.stats.input_rate_bps = int(rx_bytes * 8)
            port.stats.output_rate_bps = int(tx_bytes * 8)

            # Broadcast portion
            bc_pkts = int(rx_pkts * bc_pct)
            port.stats.rx_broadcast += bc_pkts

            # Random errors (rare)
            if random.random() < 0.002:
                err_count = random.randint(1, 3)
                port.stats.rx_errors += err_count
                port.stats.rx_crc += err_count

            # QoS queue simulation
            cos = port.qos_default_cos if port.qos_trust else 0
            q = min(cos, 7)
            port.qos_queues[q]["packets"] += rx_pkts
            if port.utilization_pct("rx") > 95:
                drops = random.randint(1, 10)
                port.qos_queues[q]["drops"] += drops

            # MAC learning simulation
            if random.random() < 0.1:
                sim_mac = random_mac("de:ad:00")
                vlan = port.access_vlan if port.switchport_mode == "access" else 1
                self.switch.mac_table.learn(sim_mac, vlan, port.name)

        # Congestion check on uplinks
        self._check_congestion()

    def _check_congestion(self):
        for pname, port in self.switch.ports.items():
            if not port.is_up:
                continue
            for direction in ("rx", "tx"):
                util = port.utilization_pct(direction)
                if util > self._congestion_threshold:
                    if self.log:
                        self.log.warn("TRAFFIC", "CONGESTION",
                                      f"{port.name} {direction.upper()} utilization at "
                                      f"{util:.1f}% — exceeds {self._congestion_threshold}% threshold")

    # ---- simulate link flap -----------------------------------------------
    def simulate_link_flap(self, port):
        """Simulate a link flap event."""
        if self.log:
            self.log.warn("LINK", "FLAP", f"{port.name} link flap simulated")
        port.bring_down()
        time.sleep(0.5)
        if port.admin_up and not port.err_disabled:
            port.bring_up()
            self.switch.stp_engine.process_link_change(port, True)

    # ---- simulate CRC errors -----------------------------------------------
    def simulate_crc_errors(self, port, count: int = 10):
        port.stats.rx_crc += count
        port.stats.rx_errors += count
        if self.log:
            self.log.warn("LINK", "CRC_ERRORS",
                          f"{port.name}: {count} CRC errors detected")

    # ---- simulate broadcast storm -----------------------------------------
    def simulate_broadcast_storm(self, port, duration: float = 5.0):
        """Inject massive broadcast traffic."""
        if self.log:
            self.log.alert("STORM", "BROADCAST",
                           f"Broadcast storm on {port.name} — injecting traffic for {duration}s")
        start = time.time()
        while time.time() - start < duration:
            port.stats.rx_broadcast += 10000
            port.stats.rx_bytes += 10000 * 64
            port.stats.rx_packets += 10000
            port.stats.input_rate_bps = int(port.speed * 0.95)
            # Check storm control
            self.switch.security_engine.check_storm_control(port, "broadcast")
            if port.err_disabled:
                break
            time.sleep(0.5)
        if not port.err_disabled:
            port.stats.input_rate_bps = 0

    # ---- bottleneck report ------------------------------------------------
    def bottleneck_report(self) -> str:
        lines = []
        lines.append("=" * 72)
        lines.append("  BOTTLENECK / CONGESTION REPORT")
        lines.append("=" * 72)

        # Top talkers
        talkers = [(p.name, p.stats.rx_bytes + p.stats.tx_bytes,
                     p.utilization_pct("rx"), p.utilization_pct("tx"))
                    for p in self.switch.ports.values() if p.is_up]
        talkers.sort(key=lambda x: x[1], reverse=True)

        lines.append("")
        lines.append("  Top Talkers (by total bytes):")
        lines.append(f"  {'Interface':<22s} {'Total Bytes':<16s} {'RX Util%':<10s} {'TX Util%'}")
        lines.append("  " + "-" * 60)
        for name, total, rx_u, tx_u in talkers[:10]:
            lines.append(f"  {name:<22s} {format_bytes(total):<16s} {rx_u:<10.1f} {tx_u:.1f}")

        # Congested links
        congested = [(p.name, max(p.utilization_pct("rx"), p.utilization_pct("tx")))
                      for p in self.switch.ports.values()
                      if p.is_up and max(p.utilization_pct("rx"),
                                          p.utilization_pct("tx")) > self._congestion_threshold]
        lines.append("")
        if congested:
            lines.append(f"  Congested Links (>{self._congestion_threshold}% utilization):")
            for name, util in congested:
                lines.append(f"    {name}: {util:.1f}%")
        else:
            lines.append("  No congested links detected.")

        # Uplink oversubscription check
        lines.append("")
        total_access_bw = sum(p.speed for p in self.switch.ports.values()
                               if p.port_type == "GE" and p.is_up)
        total_uplink_bw = sum(p.speed for p in self.switch.ports.values()
                               if p.port_type == "10GE" and p.is_up)
        if total_uplink_bw > 0:
            ratio = total_access_bw / total_uplink_bw
            lines.append(f"  Oversubscription Ratio: {ratio:.1f}:1 "
                          f"(access {format_bps(total_access_bw)} / uplink {format_bps(total_uplink_bw)})")
            if ratio > 4:
                lines.append("  *** WARNING: High oversubscription ratio — consider additional uplinks")

        # Error summary
        lines.append("")
        err_ports = [(p.name, p.stats.rx_errors, p.stats.rx_crc, p.stats.link_flaps)
                      for p in self.switch.ports.values()
                      if p.stats.rx_errors > 0 or p.stats.link_flaps > 0]
        if err_ports:
            lines.append("  Ports with Errors:")
            lines.append(f"  {'Interface':<22s} {'RX Errors':<12s} {'CRC':<8s} {'Link Flaps'}")
            lines.append("  " + "-" * 50)
            for name, errs, crc, flaps in err_ports:
                lines.append(f"  {name:<22s} {errs:<12d} {crc:<8d} {flaps}")

        lines.append("=" * 72)
        return "\n".join(lines)

    def top_talkers(self, limit: int = 5) -> str:
        rows = []
        for p in self.switch.ports.values():
            total = p.stats.rx_bytes + p.stats.tx_bytes
            rows.append((p.name, p.stats.rx_bytes, p.stats.tx_bytes, total))
        rows.sort(key=lambda r: r[1], reverse=True)
        lines = []
        lines.append(f"{'Interface':<24s} {'RX Bytes':>14s} {'TX Bytes':>14s} {'Total':>14s}")
        lines.append("-" * 72)
        for name, rx, tx, total in rows[:limit]:
            lines.append(f"{name:<24s} {rx:>14d} {tx:>14d} {total:>14d}")
        return "\n".join(lines)

    # ---- QoS queue stats --------------------------------------------------
    def show_qos_stats(self, port) -> str:
        lines = []
        lines.append(f"QoS Queue Statistics for {port.name}:")
        lines.append(f"  Trust mode: {port.qos_trust or 'untrusted'}")
        lines.append(f"  Default CoS: {port.qos_default_cos}")
        lines.append("")
        lines.append(f"  {'Queue':<8s} {'Packets':<14s} {'Drops'}")
        lines.append("  " + "-" * 30)
        for q in range(8):
            qs = port.qos_queues[q]
            lines.append(f"  {q:<8d} {qs['packets']:<14d} {qs['drops']}")
        return "\n".join(lines)

    # ---- serialization ---------------------------------------------------
    def to_dict(self):
        return {"congestion_threshold": self._congestion_threshold}

    def from_dict(self, data):
        self._congestion_threshold = data.get("congestion_threshold", 80.0)
