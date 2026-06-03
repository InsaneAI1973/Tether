# OpenLinkHub KDE

A native Qt6 (PySide6) desktop front end for the
[OpenLinkHub](https://github.com/jurkovic-nikola/OpenLinkHub) daemon. It talks
to the same REST API the bundled web dashboard uses (`http://127.0.0.1:27003`),
but gives you a real Plasma window that inherits your Breeze theme.

## What it does

- **Dashboard** — live CPU/GPU temperature and load from the daemon.
- **Per device** — for each detected Corsair hub/AIO/peripheral:
  - lighting brightness (stepped 0–4 plus a gradual 0–100% slider)
  - per-channel **speed profile** and **RGB profile** dropdowns
  - per-channel **manual fan/pump speed** (0–100%)
  - live RPM / temperature readout, refreshed every 2 s
- Re-point the host/port in the toolbar if the daemon runs elsewhere.

It only *controls* the daemon — OpenLinkHub itself must be installed and its
service running.

## Requirements (CachyOS / Arch)

```bash
# OpenLinkHub daemon must already be installed and running:
systemctl status --user OpenLinkHub.service   # or the system unit

# This front end needs only PySide6:
sudo pacman -S --needed pyside6
```

## Run it

```bash
python3 openlinkhub_kde.py
```

## Install system-wide (optional)

```bash
sudo mkdir -p /opt/openlinkhub-kde
sudo cp openlinkhub_kde.py /opt/openlinkhub-kde/
sudo cp openlinkhub-kde.desktop /usr/share/applications/
# now searchable in the KDE launcher as "OpenLinkHub KDE"
```

## Notes

- If the window shows "Offline", the daemon isn't reachable — check the
  service and the host/port in the toolbar.
- Channel data shapes vary slightly between Corsair device families. The app
  reads the generic fields (`channelId`, `label`/`name`, `rpm`,
  `temperatureString`, `profile`, `rgb`) that every driver exposes, so unknown
  devices still appear with whatever channels they report.
- Not affiliated with Corsair or with the OpenLinkHub project.
