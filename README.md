# Process Lasso for Linux — CPU affinity and priority manager

A KDE/Linux process manager inspired by Windows Process Lasso. Built with Python + PyQt6.

## Screenshots

| Rules | ProBalance |
|---|---|
| ![Rules tab](screenshots/v2/rules.png) | ![ProBalance tab](screenshots/v2/probalance.png) |

| Settings | Log |
|---|---|
| ![Settings tab](screenshots/v2/settings.png) | ![Log tab](screenshots/v2/log.png) |

---

## Asymmetric CPU controls

Settings displays the detected CPU topology. On supported asymmetric dual-CCD
AMD X3D processors it also exposes the kernel scheduler's V-Cache/Frequency CCD
preference.

The preferred-CCD selector changes scheduler rankings while leaving every CPU
online and available to the system.

---

## Features

### Processes tab
- Live process table — sortable by CPU%, memory, PID, nice, affinity, I/O
- **Per-CPU utilization bars** — htop-style with colour ramp (green → yellow → orange → red by load)
- **CPU frequency display** — each bar shows current GHz (e.g. `4.43G`) alongside utilization %
- **Temperature tint** — bars shift orange as core temps rise (reads from hwmon/k10temp/zenpower)
- **Rolling CPU history chart** — 4-minute area graph above the bars, colour-coded by load
- Filter bar (Ctrl+F) — live search by process name or PID
- Right-click context menu: Set affinity, Set nice priority, Set I/O priority, Add rule, Kill / Force Kill
- Multi-select with Shift/Ctrl+click; Delete key to kill selected processes
- Column visibility toggle; cmdline tooltip on process name

### Rules tab
- Pin any process to specific CPU cores, permanently enforced across reboots
- Match by **name contains**, **exact name**, or **regular expression**
- **Visual CPU affinity picker** — topology-aware checkbox grid, no manual range typing required
  - Quick-select buttons: **All**, **None**, **CCD0 (V-Cache)**, **CCD1**, **CCD0 (no SMT)**
  - Pre-fills from a running process via "Select from running processes…"
- Per-rule nice priority (−20 to 19) and I/O priority (class + level)
- Enable/disable individual rules without deleting them
- Export rules to JSON / Import from JSON
- 14 built-in rule presets (Steam, Wine/Proton, OBS, Discord, browsers, compilers, etc.)

### ProBalance tab
- Automatically throttles CPU-hogging background processes when system load spikes
- Configurable CPU threshold, throttle nice value, and cooldown period
- Live count of currently throttled processes shown as a badge on the tab label
- Restore original priority the moment load drops back to normal

### Settings tab
- Detected CPU topology
- AMD X3D scheduler preferred-CCD selection when supported
- Default CPU affinity applied to all new processes
- Monitor polling interval (0.5 s – 10 s)
- Start minimized to tray on launch
- Systemd user service autostart toggle (no root required)
- Privileged helper status and install/update action

### System tray
- Minimize to tray on window close
- Tray tooltip shows live average CPU %

---

## Requirements

- Python 3.8+
- `psutil >= 5.9`
- `PyQt6 >= 6.4`
- Linux kernel ≥ 4.1 (sysfs CPU hotplug)
- `sudo` with a NOPASSWD rule for the sysfs helper (set up via Settings)

---

## Install

```bash
git clone https://github.com/FranzJeger/process-lasso-linux.git
cd process-lasso-linux
bash install.sh
```

The installer detects your package manager and prints the correct install command for any missing dependency.

The process is named `process-lasso` by default. To customize it, change
`PROCESS_NAME` in `app_identity.py` and run the installer again.

## Distro compatibility

| Distro | Package manager | psutil | PyQt6 |
|---|---|---|---|
| Arch / Manjaro | pacman | `python-psutil` | `python-pyqt6` |
| Ubuntu / Debian | apt | `python3-psutil` | `python3-pyqt6` |
| Fedora / RHEL | dnf | `python3-psutil` | `python3-PyQt6` |
| openSUSE | zypper | `python3-psutil` | `python3-pyqt6` |
| Any | pip | `psutil` | `PyQt6` |

---

## Asymmetric CPU settings

### AMD X3D — multi-CCD only

Only applies to CPUs with **two CCDs where one has 3D V-Cache and the other does not**:

| CPU | Cores | 3D V-Cache CCD |
|---|---|---|
| Ryzen 9 7900X3D | 12 | CCD0 (6 cores, large L3) |
| Ryzen 9 7950X3D | 16 | CCD0 (8 cores, large L3) |
| Ryzen 9 9900X3D | 12 | CCD0 (6 cores, large L3) |
| Ryzen 9 9950X3D | 16 | CCD0 (8 cores, large L3) |

Single-CCD X3D chips (5800X3D, 7800X3D, 9800X3D) have all cores on the same die, so there is no CCD preference to select.

The detector finds the CCD with the larger L3 cache and identifies those cores
as V-Cache cores. Use **Settings → AMD X3D — Scheduler Preferred CCD** to change
the scheduler ranking without taking either CCD offline.

### Intel Hybrid (12th gen+, Core Ultra)

The detector identifies P-cores by their higher maximum frequency for
topology-aware affinity selection.

---

## Built with AI

This project was built entirely with [Claude](https://claude.ai) (Anthropic). Every line of Python, the GUI, the sysfs integration, the helper binary — all of it was written through a conversation with an AI assistant. No apologies. It works, it's fast, and the dark theme slaps.


---

## License

MIT — see [LICENSE](LICENSE).
