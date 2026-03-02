"""Power over Ethernet manager — IEEE 802.3bt budget tracking."""

import threading
from switch_simulator.utils import green, yellow, red


# IEEE 802.3bt PoE device classes with max wattage
POE_CLASSES = {
    0: 15.4,   # Class 0 (default)
    1: 4.0,    # Class 1
    2: 7.0,    # Class 2
    3: 15.4,   # Class 3
    4: 30.0,   # Class 4 (802.3at)
    5: 45.0,   # Class 5 (802.3bt Type 3)
    6: 60.0,   # Class 6 (802.3bt Type 3)
    7: 75.0,   # Class 7 (802.3bt Type 4)
    8: 90.0,   # Class 8 (802.3bt Type 4)
}

# Pre-defined PoE device profiles
POE_DEVICES = {
    "ip-camera": {"class": 3, "draw": 12.5, "type": "IP Camera"},
    "wifi7-ap": {"class": 6, "draw": 51.0, "type": "Wi-Fi 7 AP"},
    "voip-phone": {"class": 2, "draw": 6.5, "type": "VoIP Phone"},
    "iot-sensor": {"class": 1, "draw": 3.2, "type": "IoT Sensor"},
    "ptz-camera": {"class": 5, "draw": 40.0, "type": "PTZ Camera"},
    "wireless-ap": {"class": 4, "draw": 25.5, "type": "Wireless AP"},
}

PRIORITY_ORDER = {"critical": 0, "high": 1, "low": 2}


class PoEManager:
    """PoE budget management with per-port tracking and priority-based cutoff."""

    def __init__(self, switch, total_budget: float = 370.0, log_engine=None):
        self.switch = switch
        self._total_budget = float(total_budget)
        self.log = log_engine
        self._lock = threading.Lock()

    @property
    def total_budget(self) -> float:
        return self._total_budget

    @total_budget.setter
    def total_budget(self, value: float):
        self._total_budget = max(0.0, float(value))
        self._enforce_budget()

    @property
    def used_power(self) -> float:
        return sum(p.poe_allocated_w for p in self.switch.ports.values()
                   if p.poe_enabled and p.poe_allocated_w > 0)

    @property
    def available_power(self) -> float:
        return max(0.0, self.total_budget - self.used_power)

    def _enforce_budget(self):
        while self.used_power > self.total_budget:
            powered = [p for p in self.switch.ports.values() if p.poe_allocated_w > 0]
            if not powered:
                break
            powered.sort(key=lambda p: (PRIORITY_ORDER.get(p.poe_priority, 2), p.poe_allocated_w), reverse=True)
            victim = powered[0]
            if self.log:
                self.log.warn("POE", "BUDGET_ENFORCE",
                              f"Depowering {victim.name} ({victim.poe_allocated_w:.1f}W, "
                              f"priority={victim.poe_priority}) to enforce budget {self.total_budget:.1f}W")
            victim.poe_allocated_w = 0.0
            victim.poe_device_class = None
            victim.poe_device_type = ""
            victim.poe_max_w = 0.0

    # ---- device connect / disconnect --------------------------------------
    def connect_device(self, port, device_key: str = None,
                       device_class: int = 0, power_draw: float = 0.0,
                       device_type: str = "") -> str:
        """Attempt to power a PoE device. Returns status message."""
        if not port.poe_enabled:
            return f"% PoE is disabled on {port.name}"

        if device_key and device_key in POE_DEVICES:
            prof = POE_DEVICES[device_key]
            device_class = prof["class"]
            power_draw = prof["draw"]
            device_type = prof["type"]

        max_class_w = POE_CLASSES.get(device_class, 15.4)
        actual_draw = min(power_draw, max_class_w) if power_draw > 0 else max_class_w

        with self._lock:
            if actual_draw > self.available_power:
                # Try to shed lower-priority ports
                freed = self._shed_for_priority(port.poe_priority, actual_draw - self.available_power)
                if actual_draw > self.available_power:
                    if self.log:
                        self.log.warn("POE", "BUDGET_EXCEED",
                                      f"Cannot power {port.name}: needs {actual_draw:.1f}W, "
                                      f"available {self.available_power:.1f}W")
                    return (f"% Insufficient PoE budget for {port.name} "
                            f"(need {actual_draw:.1f}W, available {self.available_power:.1f}W)")

            port.poe_allocated_w = actual_draw
            port.poe_device_class = device_class
            port.poe_device_type = device_type
            port.poe_max_w = max_class_w

        if self.log:
            self.log.info("POE", "DEVICE_ON",
                          f"{device_type or 'Device'} powered on {port.name}: "
                          f"{actual_draw:.1f}W (class {device_class})")
        return ""

    def disconnect_device(self, port):
        with self._lock:
            old = port.poe_allocated_w
            port.poe_allocated_w = 0.0
            port.poe_device_class = None
            port.poe_device_type = ""
            port.poe_max_w = 0.0
        if self.log and old > 0:
            self.log.info("POE", "DEVICE_OFF",
                          f"PoE device disconnected on {port.name}: freed {old:.1f}W")

    def _shed_for_priority(self, requester_priority: str, needed: float) -> float:
        """Shed lower-priority ports to free budget. Returns watts freed."""
        req_order = PRIORITY_ORDER.get(requester_priority, 2)
        candidates = []
        for p in self.switch.ports.values():
            if p.poe_allocated_w > 0:
                p_order = PRIORITY_ORDER.get(p.poe_priority, 2)
                if p_order > req_order:
                    candidates.append(p)
        # Sort by priority (lowest first), then by power (highest first)
        candidates.sort(key=lambda p: (-PRIORITY_ORDER.get(p.poe_priority, 2), -p.poe_allocated_w))

        freed = 0.0
        for p in candidates:
            if freed >= needed:
                break
            freed += p.poe_allocated_w
            if self.log:
                self.log.warn("POE", "POWER_SHED",
                              f"Shedding {p.name} ({p.poe_allocated_w:.1f}W, priority={p.poe_priority}) "
                              f"to free budget")
            p.poe_allocated_w = 0.0
            p.poe_device_type = ""
        return freed

    # ---- show power inline ------------------------------------------------
    def show_power_inline(self) -> str:
        lines = []
        lines.append(f"Available: {self.total_budget:.1f}(w)  Used: {self.used_power:.1f}(w)  "
                      f"Remaining: {self.available_power:.1f}(w)")
        lines.append("")
        lines.append(f"{'Interface':<22s} {'Admin':<8s} {'Oper':<10s} {'Power(w)':<10s} "
                      f"{'Device':<16s} {'Class':<8s} {'Priority'}")
        lines.append("-" * 90)
        for pname in sorted(self.switch.ports):
            p = self.switch.ports[pname]
            if p.port_type == "10GE":
                continue  # uplink ports don't do PoE
            admin = "auto" if p.poe_enabled else "off"
            oper = "on" if p.poe_allocated_w > 0 else "off"
            pwr = f"{p.poe_allocated_w:.1f}" if p.poe_allocated_w > 0 else "0.0"
            dev = p.poe_device_type or "n/a"
            cls = str(p.poe_device_class) if p.poe_device_class is not None else "n/a"
            lines.append(
                f"{p.short_name:<22s} {admin:<8s} {oper:<10s} {pwr:<10s} "
                f"{dev:<16s} {cls:<8s} {p.poe_priority}"
            )
        return "\n".join(lines)

    def show_power_inline_detail(self, port) -> str:
        lines = []
        lines.append(f"Interface: {port.name}")
        lines.append(f"  Inline Power Mode: {'auto' if port.poe_enabled else 'off'}")
        lines.append(f"  Operational status: {'on' if port.poe_allocated_w > 0 else 'off'}")
        lines.append(f"  Device Detected: {'yes' if port.poe_device_type else 'no'}")
        lines.append(f"  Device Type: {port.poe_device_type or 'n/a'}")
        lines.append(f"  IEEE Class: {port.poe_device_class if port.poe_device_class is not None else 'n/a'}")
        lines.append(f"  Power drawn: {port.poe_allocated_w:.1f} Watts")
        lines.append(f"  Max power:   {port.poe_max_w:.1f} Watts")
        lines.append(f"  Priority:    {port.poe_priority}")
        lines.append(f"  Admin Value: {self.total_budget:.1f} Watts (system)")
        return "\n".join(lines)

    # ---- serialization ---------------------------------------------------
    def to_dict(self):
        return {"total_budget": self.total_budget}

    def from_dict(self, data):
        self.total_budget = data.get("total_budget", 370.0)
