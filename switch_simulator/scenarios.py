"""Pre-configured lab scenarios for the switch simulator."""

from switch_simulator.utils import canonical_intf, format_mac, random_mac


SCENARIOS = {
    "default_lab":        "3 VLANs, 8 devices (PoE + non-PoE), trunk uplink, port-security",
    "vlan_segmentation":  "Strict VLAN segmentation with private VLANs",
    "poe_overload":       "PoE budget overload test — more devices than budget allows",
    "mac_flood_response": "Port-security configured, then MAC flood attack runs",
}


def load_scenario(switch, name: str) -> str:
    """Load a named scenario onto the switch. Returns status message."""
    loader = _LOADERS.get(name.lower())
    if not loader:
        return (f"% Unknown scenario '{name}'. Available:\n" +
                "\n".join(f"  {k:<24s} {v}" for k, v in SCENARIOS.items()))
    try:
        return loader(switch)
    except Exception as e:
        return f"% Error loading scenario '{name}': {e}"


# ─────────────────────────────────────────────────────────────────────────
# DEFAULT LAB — 3 VLANs, 8 connected devices, trunk uplink, port-security
# ─────────────────────────────────────────────────────────────────────────
def _load_default_lab(sw) -> str:
    log = sw.log_engine
    log.info("SCENARIO", "LOAD", "Loading default_lab scenario...")

    # ── Create VLANs ──────────────────────────────────────────────────────
    sw.vlan_db.create(10, "DATA")
    sw.vlan_db.create(20, "VOICE")
    sw.vlan_db.create(99, "MANAGEMENT")

    # ── Management ────────────────────────────────────────────────────────
    sw.mgmt_vlan = 99
    sw.mgmt_ip = "192.168.99.1"
    sw.mgmt_mask = "255.255.255.0"
    sw.mgmt_gateway = "192.168.99.254"

    # ── Trunk uplink: Te0/1 ───────────────────────────────────────────────
    trunk = sw.ports["TenGigabitEthernet0/1"]
    trunk.switchport_mode = "trunk"
    trunk.trunk_native_vlan = 1
    trunk.trunk_allowed_vlans = {1, 10, 20, 99}
    trunk.description = "Uplink to Core"
    trunk.admin_up = True
    trunk.bring_up()
    # Simulated CDP neighbour on trunk
    sw.neighbor_mgr.add_cdp_neighbor(
        trunk.name,
        device_id="CoreSwitch.lab.local",
        capability="S I",
        platform="WS-C9300-48P",
        remote_intf="TenGigabitEthernet1/0/1",
        ip_address="10.0.0.1",
    )
    sw.neighbor_mgr.add_lldp_neighbor(
        trunk.name,
        system_name="CoreSwitch",
        port_desc="Te1/0/1",
        mgmt_ip="10.0.0.1",
    )

    # ── Access ports with devices ─────────────────────────────────────────
    device_configs = [
        # (port, vlan, description, poe_device, device_mac, device_ip)
        ("GigabitEthernet0/1", 10, "PC-Finance-1",       None,          "aabb.cc00.0001", "192.168.10.11"),
        ("GigabitEthernet0/2", 10, "PC-Finance-2",       None,          "aabb.cc00.0002", "192.168.10.12"),
        ("GigabitEthernet0/3", 20, "VoIP-Phone-1",       "voip-phone",  "aabb.cc00.0003", "192.168.20.11"),
        ("GigabitEthernet0/4", 20, "VoIP-Phone-2",       "voip-phone",  "aabb.cc00.0004", "192.168.20.12"),
        ("GigabitEthernet0/5", 10, "IP-Camera-Lobby",    "ip-camera",   "aabb.cc00.0005", "192.168.10.51"),
        ("GigabitEthernet0/6", 10, "WiFi-AP-Floor1",     "wifi7-ap",    "aabb.cc00.0006", "192.168.10.61"),
        ("GigabitEthernet0/7", 10, "IoT-Sensor-HVAC",    "iot-sensor",  "aabb.cc00.0007", "192.168.10.71"),
        ("GigabitEthernet0/8", 10, "PC-HR-1",            None,          "aabb.cc00.0008", "192.168.10.13"),
    ]

    for (pname, vlan, desc, poe_dev, mac_str, ip) in device_configs:
        port = sw.ports[pname]
        port.switchport_mode = "access"
        port.access_vlan = vlan
        port.description = desc
        port.admin_up = True
        port.bring_up()
        port.portfast = True

        # Port security on all access ports
        port.security.enabled = True
        port.security.maximum = 2
        port.security.violation_mode = "shutdown"
        port.security.sticky = True
        port.bpdu_guard = True

        # Storm control on access ports
        port.storm_control.broadcast_level = 20.0
        port.storm_control.multicast_level = 20.0

        # Learn device MAC
        mac_norm = mac_str.replace(".", "").replace(":", "").replace("-", "").lower()
        sw.mac_table.learn(mac_norm, vlan, pname, "sticky")
        port.security.sticky_macs.add(mac_norm)

        # ARP entry
        sw.arp_table.add(ip, mac_norm, vlan, pname)

        # PoE device
        if poe_dev:
            err = sw.poe_manager.connect_device(port, device_key=poe_dev)
            if err:
                log.warn("SCENARIO", "POE_FAIL", err)

        # Add some traffic
        if port.is_up:
            sw.traffic_engine.set_traffic(pname, avg_mbps=50.0 + (vlan * 2),
                                           burst_pct=15.0, broadcast_pct=1.5)

    # ── DHCP snooping on data VLAN ────────────────────────────────────────
    sw.security_engine.dhcp_snooping_enabled = True
    sw.security_engine.dhcp_snooping_vlans = {10, 20}
    trunk.dhcp_snooping_trusted = True

    # ── DAI on data VLAN ──────────────────────────────────────────────────
    sw.security_engine.dai_enabled = True
    sw.security_engine.dai_vlans = {10, 20}

    # ── Add DHCP bindings for the lab devices ─────────────────────────────
    for (pname, vlan, desc, poe_dev, mac_str, ip) in device_configs:
        mac_norm = mac_str.replace(".", "").replace(":", "").replace("-", "").lower()
        sw.security_engine.process_dhcp(
            sw.ports[pname], mac_norm, ip, vlan, is_server=False
        )

    # ── STP re-election ───────────────────────────────────────────────────
    sw.stp_engine.elect(
        list(sw.vlan_db.all_vlans().keys()),
        list(sw.ports.values())
    )

    lines = [
        "Scenario 'default_lab' loaded successfully.",
        f"  VLANs: 10 (DATA), 20 (VOICE), 99 (MANAGEMENT)",
        f"  Trunk: Te0/1 -> CoreSwitch (allowed VLANs 1,10,20,99)",
        f"  Devices: 8 connected (4 PoE: 2 VoIP, 1 IP Camera, 1 WiFi 7 AP, 1 IoT)",
        f"  Security: port-security (sticky, max 2, shutdown), BPDU guard",
        f"  DHCP snooping: enabled on VLANs 10,20",
        f"  DAI: enabled on VLANs 10,20",
        f"  PoE budget: {sw.poe_manager.used_power:.1f}W / {sw.poe_manager.total_budget:.1f}W",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# VLAN SEGMENTATION scenario
# ─────────────────────────────────────────────────────────────────────────
def _load_vlan_segmentation(sw) -> str:
    sw.vlan_db.create(100, "SERVERS")
    sw.vlan_db.create(200, "USERS")
    sw.vlan_db.create(300, "GUEST")
    sw.vlan_db.create(400, "IOT")

    # Private VLANs
    sw.vlan_db.create(501, "PVLAN-ISOLATED")
    sw.vlan_db.set_private_vlan(501, "isolated")
    sw.vlan_db.create(502, "PVLAN-COMMUNITY")
    sw.vlan_db.set_private_vlan(502, "community")
    sw.vlan_db.set_private_vlan(100, "primary", {501, 502})

    # Trunk
    trunk = sw.ports["TenGigabitEthernet0/1"]
    trunk.switchport_mode = "trunk"
    trunk.trunk_allowed_vlans = {1, 100, 200, 300, 400, 501, 502}
    trunk.admin_up = True
    trunk.bring_up()

    # Assign ports
    for i in range(1, 7):
        p = sw.ports[f"GigabitEthernet0/{i}"]
        p.switchport_mode = "access"
        p.access_vlan = 200
        p.admin_up = True
        p.bring_up()
        p.portfast = True

    for i in range(7, 13):
        p = sw.ports[f"GigabitEthernet0/{i}"]
        p.switchport_mode = "access"
        p.access_vlan = 300
        p.admin_up = True
        p.bring_up()
        p.portfast = True

    for i in range(13, 19):
        p = sw.ports[f"GigabitEthernet0/{i}"]
        p.switchport_mode = "access"
        p.access_vlan = 400
        p.admin_up = True
        p.bring_up()
        p.portfast = True

    sw.stp_engine.elect(list(sw.vlan_db.all_vlans().keys()),
                         list(sw.ports.values()))
    return ("Scenario 'vlan_segmentation' loaded.\n"
            "  VLANs: 100 (SERVERS), 200 (USERS, Gi0/1-6), 300 (GUEST, Gi0/7-12),\n"
            "         400 (IOT, Gi0/13-18), 501 (PVLAN-ISOLATED), 502 (PVLAN-COMMUNITY)\n"
            "  Trunk: Te0/1 (all VLANs)")


# ─────────────────────────────────────────────────────────────────────────
# POE OVERLOAD scenario
# ─────────────────────────────────────────────────────────────────────────
def _load_poe_overload(sw) -> str:
    sw.vlan_db.create(10, "DATA")

    # Connect a bunch of high-power devices
    devices = [
        ("GigabitEthernet0/1",  "wifi7-ap",   "critical", "WiFi7-AP-1"),
        ("GigabitEthernet0/2",  "wifi7-ap",   "critical", "WiFi7-AP-2"),
        ("GigabitEthernet0/3",  "wifi7-ap",   "high",     "WiFi7-AP-3"),
        ("GigabitEthernet0/4",  "wifi7-ap",   "high",     "WiFi7-AP-4"),
        ("GigabitEthernet0/5",  "wifi7-ap",   "high",     "WiFi7-AP-5"),
        ("GigabitEthernet0/6",  "wifi7-ap",   "low",      "WiFi7-AP-6"),
        ("GigabitEthernet0/7",  "wifi7-ap",   "low",      "WiFi7-AP-7"),
        ("GigabitEthernet0/8",  "ptz-camera", "low",      "PTZ-Camera-1"),
        ("GigabitEthernet0/9",  "ptz-camera", "low",      "PTZ-Camera-2"),
        ("GigabitEthernet0/10", "ptz-camera", "low",      "PTZ-Camera-3"),
    ]

    results = []
    for (pname, dev_key, priority, desc) in devices:
        port = sw.ports[pname]
        port.switchport_mode = "access"
        port.access_vlan = 10
        port.description = desc
        port.poe_priority = priority
        port.admin_up = True
        port.bring_up()
        err = sw.poe_manager.connect_device(port, device_key=dev_key)
        status = "OK" if not err else err.strip("% ")
        results.append(f"  {pname:<24s} {desc:<16s} {priority:<10s} {status}")

    lines = [
        "Scenario 'poe_overload' loaded.",
        f"  Total budget: {sw.poe_manager.total_budget:.1f}W",
        f"  Used: {sw.poe_manager.used_power:.1f}W",
        f"  Available: {sw.poe_manager.available_power:.1f}W",
        "",
        "  Device connection results:",
    ] + results
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# MAC FLOOD RESPONSE scenario
# ─────────────────────────────────────────────────────────────────────────
def _load_mac_flood_response(sw) -> str:
    sw.vlan_db.create(10, "DATA")

    # Set up ports with security
    for i in range(1, 5):
        p = sw.ports[f"GigabitEthernet0/{i}"]
        p.switchport_mode = "access"
        p.access_vlan = 10
        p.admin_up = True
        p.bring_up()
        p.portfast = True
        p.security.enabled = True
        p.security.maximum = 3
        p.security.violation_mode = "shutdown"
        p.security.sticky = True
        p.bpdu_guard = True
        p.storm_control.broadcast_level = 10.0

    # Simulate some legit MACs
    for i in range(1, 5):
        pname = f"GigabitEthernet0/{i}"
        mac = f"aabb{i:02d}000001"
        sw.mac_table.learn(mac, 10, pname, "sticky")
        sw.ports[pname].security.sticky_macs.add(mac)

    return ("Scenario 'mac_flood_response' loaded.\n"
            "  Ports Gi0/1-4 configured with port-security (max 3, sticky, shutdown).\n"
            "  1 MAC learned on each port.\n"
            "  Run: attack simulate mac-flood port GigabitEthernet0/1\n"
            "  to test security response.")


# ─────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────
_LOADERS = {
    "default_lab":        _load_default_lab,
    "vlan_segmentation":  _load_vlan_segmentation,
    "poe_overload":       _load_poe_overload,
    "mac_flood_response": _load_mac_flood_response,
}
