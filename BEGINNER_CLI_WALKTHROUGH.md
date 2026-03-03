# 🌱 Beginner CLI Walkthrough (Zero Experience Needed)

This guide is for someone using a switch simulator for the first time.

You will learn:
- what a switch does
- what Layer 2 means
- what an Ethernet frame is
- how a MAC address table is learned

---

## 0) Start the simulator

```bash
python main.py --scenario default_lab
```

You should see a prompt like:

```text
Switch>
```

---

## 1) Move into privileged mode

Type:

```text
enable
```

Prompt changes from:
- `Switch>` (user mode)
to:
- `Switch#` (privileged mode)

Why this matters:
- Most inspection and configuration commands are run from `Switch#`.

---

## 2) See physical/logical interfaces

Type:

```text
show interfaces status
```

Look for:
- interface names (example: `GigabitEthernet0/1`)
- link state (up/down)
- VLAN assignment

Why this matters:
- A switch forwards traffic through interfaces (ports). This is your hardware view.

---

## 3) Check VLAN segmentation

Type:

```text
show vlan brief
```

Look for:
- VLAN IDs (example: 1, 10, 20)
- port membership per VLAN

Why this matters:
- VLANs split one switch into separate Layer 2 broadcast domains.

---

## 4) Inspect the MAC address table

Type:

```text
show mac address-table
```

Look for entries shaped like:

```text
<MAC Address>  ->  <Port>
```

Why this matters:
- This table is how a switch decides where to forward frames.
- Known destination MAC = send to one port.
- Unknown destination MAC = flood in that VLAN.

---

## 5) Understand with built-in explain

Type:

```text
explain show mac address-table
```

Why this matters:
- The simulator explains commands in plain English.
- Use `explain <command>` any time output feels unclear.

---

## 6) Map the theory quickly

- **Switch layer:** mostly OSI Layer 2 (Data Link)
- **Unit of forwarding:** Ethernet frame
- **Frame key fields:** destination MAC, source MAC, payload, FCS
- **Decision source:** MAC address table (`MAC -> Port`)

---

## 7) Optional mini experiment (watch table changes)

Run this command multiple times while using the simulator:

```text
show mac address-table
```

Then trigger activity (normal traffic or scenario actions) and run it again.

What you’ll notice:
- new MAC entries appear when traffic is seen
- entries may age out after inactivity

---

## 8) Next commands to learn after this

```text
show spanning-tree
show port-security
show power inline
```

If you complete this guide once, you already understand the core behavior of Layer 2 switching.
