# 🔀 Enterprise Network Switch Simulator

<div align="center">

**A full Cisco IOS-style CLI switch simulator — no hardware, no license, just Python.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey?style=for-the-badge)]()
[![Version](https://img.shields.io/badge/Version-2.6-orange?style=for-the-badge)]()

</div>

---

## 🧠 What Is This?

A production-quality, terminal-based network switch simulator that mirrors real Cisco IOS syntax and behavior. Designed for **IT professionals**, **network engineers**, and **students** who want to design, test, and break network configurations in a completely safe, zero-risk environment.

> 💡 *Configure VLANs, simulate MAC flood attacks, manage PoE budgets, test STP topologies — all from your terminal, all without touching physical hardware.*

---

## 🌱 Beginner Primer (If You're Brand New)

If you're completely new to networking, start here first.

➡️ Full step-by-step lesson: **[Beginner CLI Walkthrough](BEGINNER_CLI_WALKTHROUGH.md)**

### 1) What is a switch?

A **network switch** is like a smart traffic director inside a local network (LAN).

- It connects devices like PCs, printers, servers, and Wi-Fi access points.
- It forwards data only to the correct destination port (not to everyone).
- This makes communication faster and safer than old shared-hub behavior.

### 2) Which layer does a switch work on?

Most switching happens at **OSI Layer 2 (Data Link layer)**.

- Layer 2 uses **MAC addresses** to decide where frames should go.
- Some enterprise switches can also do Layer 3 routing, but this simulator focuses mainly on realistic Layer 2 switch behavior first.

### 3) What is an Ethernet frame?

Inside a LAN, devices send data in an **Ethernet frame**.

Core parts of a frame:

- **Destination MAC**: where the frame should go
- **Source MAC**: who sent it
- **Type/Length**: what protocol payload follows
- **Payload**: actual data
- **FCS**: error-check value

In simple terms: a frame is the "envelope" used for local network delivery.

### 4) What is a MAC address table?

A switch builds a **MAC address table** (also called CAM table) as it sees incoming traffic.

- It learns: `MAC address -> Port`
- If destination MAC is known, it sends frame only to that port (**unicast forwarding**)
- If destination MAC is unknown, it sends to multiple ports in the VLAN (**flooding**)
- Old entries age out after a timer if no traffic is seen

This learning process is the core of how switching works.

### 5) First 5-minute learning flow in this simulator

Run the default lab:

```bash
python main.py --scenario default_lab
```

Then try these commands:

```bash
Switch> enable
Switch# show interfaces status
Switch# show mac address-table
Switch# show vlan brief
Switch# explain show mac address-table
```

What to watch for:

- Ports that are up/down
- Which VLAN a port belongs to
- Which MAC addresses are learned on which ports
- How table entries change after traffic/attacks

If you're new, repeat this cycle until the output feels familiar. Then move to VLAN and STP labs.

---

## ⚡ Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Launch the simulator
python main.py

# Launch with a pre-loaded lab scenario
python main.py --scenario default_lab
```

---

## ✨ Features

### 🖥️ Full IOS-Style CLI
- User → Privileged → Config → Interface → VLAN mode transitions
- Command abbreviations (`sh int`, `conf t`, `wr`)
- Context-sensitive `?` help and tab completion
- IOS-accurate error messages with `^` marker
- `explain <command>` — plain-English breakdown of any command

### 🔌 Ports & Interfaces
- **28 ports** — 24× GigabitEthernet + 4× TenGigabitEthernet uplinks
- Per-port speed, duplex, description, admin up/down
- Live rx/tx counters, utilization %, error stats

### 🏷️ VLANs & Trunking
- Create, delete, name, suspend VLANs (range 1–4094)
- 802.1Q trunks, native VLAN config, allowed VLAN lists
- Private VLANs (isolated / community / promiscuous)

### 🌳 Spanning Tree (STP)
- Rapid-PVST+ with root bridge election
- PortFast, BPDU Guard, Root Guard
- Per-VLAN STP priorities and topology change notifications

### 🔒 Security Features
| Feature | Description |
|---|---|
| 🛡️ Port Security | Max MACs, sticky learning, violation modes (shutdown / restrict / protect) |
| 🚫 MAC Flood Defense | Configurable threshold, auto-shutdown, real-time alerting |
| 🍀 DHCP Snooping | Trusted/untrusted ports, binding table, rate limiting |
| 🔍 Dynamic ARP Inspection | Validates ARP against DHCP binding table |
| 🔑 802.1X Auth | Port authentication states (unauthorized / authorized / guest VLAN) |
| ⛈️ Storm Control | Broadcast/multicast/unicast thresholds with configurable actions |
| 🧱 IP Source Guard | Validates source IP against DHCP bindings |

### ⚡ PoE Management (IEEE 802.3bt)
- **370W** total budget (configurable)
- Device classes **0–8** with accurate wattage values
- Priority-based power shedding (critical / high / low)
- Simulate IP cameras, Wi-Fi 7 APs, VoIP phones, IoT sensors
- Real-time budget tracking: used / available / reserved

### 📊 Traffic & Bottleneck Simulation
- Background traffic threads per port with realistic utilization
- Uplink congestion detection (alerts at >80%)
- `show bottleneck` — identifies oversubscribed links
- `show top-talkers` — top 5 ports by traffic volume
- Link flap, CRC error, and broadcast storm simulation

### 💥 Attack Simulation
```bash
Switch# attack simulate mac-flood port GigabitEthernet0/1
Switch# attack simulate arp-spoof port GigabitEthernet0/3
Switch# attack simulate dhcp-starvation port GigabitEthernet0/2
```
Each attack runs in real time with live syslog output showing detection and response.

### 💾 Config Persistence
- `write memory` / `copy run start` / `erase startup-config`
- Save and load as **JSON** or **YAML**
- Sticky MACs survive save/reload cycles
- Full running-config and startup-config diff support

---

## 🚀 Command Examples

```
Switch> enable
Switch# show version
Switch# configure terminal
Switch(config)# vlan 10
Switch(config-vlan)# name DATA
Switch(config-vlan)# exit

Switch(config)# interface GigabitEthernet0/1
Switch(config-if:Gi0/1)# switchport mode access
Switch(config-if:Gi0/1)# switchport access vlan 10
Switch(config-if:Gi0/1)# switchport port-security
Switch(config-if:Gi0/1)# switchport port-security maximum 2
Switch(config-if:Gi0/1)# switchport port-security violation shutdown
Switch(config-if:Gi0/1)# switchport port-security mac-address sticky
Switch(config-if:Gi0/1)# spanning-tree portfast
Switch(config-if:Gi0/1)# spanning-tree bpduguard enable
Switch(config-if:Gi0/1)# no shutdown
Switch(config-if:Gi0/1)# end

Switch# show interfaces status
Switch# show vlan brief
Switch# show mac address-table
Switch# show spanning-tree
Switch# show port-security
Switch# show power inline
Switch# write memory

Switch# attack simulate mac-flood port GigabitEthernet0/1
Switch# bottleneck
Switch# explain show spanning-tree
Switch# scenario load default_lab
```

---

## 🧪 Lab Scenarios

| Scenario | Description |
|---|---|
| 🏫 `default_lab` | 3 VLANs, 8 devices (PoE mix), trunk uplink, port-security active |
| 🔐 `vlan_segmentation` | Strict VLAN segmentation with private VLAN isolation |
| 🔋 `poe_overload` | PoE budget overload with priority-based shedding demo |
| 🚨 `mac_flood_response` | Live MAC flood attack with detection and auto-response |

> Load any scenario with: `python main.py --scenario <name>`

---

## 🏗️ Architecture

```
switch_simulator/
│
├── 🚪 cli.py               # Full IOS CLI — all modes & commands
├── 🔀 switch.py            # Core switch orchestrator
├── 🔌 port.py              # Port model with all sub-configurations
│
├── 🏷️  vlan_db.py           # VLAN database (1–4094)
├── 📋 mac_table.py         # MAC table with aging & eviction
├── 🗺️  arp_table.py         # ARP table (static + dynamic)
│
├── 🌳 stp_engine.py        # Rapid-PVST+ spanning tree engine
├── 🔒 security_engine.py   # Port-security, DHCP snooping, DAI, storm control
├── ⚡ poe_manager.py       # PoE budget manager (IEEE 802.3bt)
├── 📊 traffic_engine.py    # Background traffic simulation threads
│
├── 🔍 span_manager.py      # SPAN/RSPAN port mirroring
├── 🔗 port_channel.py      # LACP/PAgP EtherChannel aggregation
├── 📡 neighbors.py         # CDP/LLDP neighbor simulation
├── 💥 attacks.py           # Attack simulator
├── 🧪 scenarios.py         # Pre-built lab scenarios
│
├── 📝 log_engine.py        # Syslog with severity levels (EMERG–DEBUG)
├── 🎨 utils.py             # Colors, formatting, constants
├── ⚙️  __main__.py          # python -m support
└── 📦 __init__.py          # Package marker
```

---

## 🎯 Who Is This For?

| 👤 User | 💼 Use Case |
|---|---|
| 🎓 Students | Learn IOS CLI and networking concepts without physical gear |
| 🔧 Junior Engineers | Practice VLAN, STP, and security configs safely |
| 🏢 Enterprise IT | Test change management scenarios before live deployment |
| 🔴 Security Teams | Simulate and validate defenses against Layer 2 attacks |
| 🛠️ Network Architects | Prototype designs before hardware procurement |

---

## 📋 Requirements

```
Python     3.10+
colorama   0.4.x    # Terminal color output
pyyaml     6.x      # YAML config support
readline              # Tab completion (built-in on Linux/macOS)
```

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

<div align="center">

**Built for the terminal. Built for engineers. Built to break things safely.**

⭐ *Star this repo if it helped you learn something!*

</div>