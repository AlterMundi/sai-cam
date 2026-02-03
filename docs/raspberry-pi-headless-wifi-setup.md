# Raspberry Pi Headless WiFi Setup — Lessons Learned

Hard-won knowledge from debugging a headless RPi WiFi setup on **Raspberry Pi OS based on Debian 13 (Trixie)**, December 2025 image.

## TL;DR

The old `wpa_supplicant.conf`-on-boot-partition trick is dead. Modern RPi OS uses cloud-init + NetworkManager. Write a `.nmconnection` file directly and disable cloud-init network config.

---

## 1. `wpa_supplicant.conf` on `/boot` No Longer Works

**Applies to**: Raspberry Pi OS Bookworm (2023) and later (including Trixie).

The classic headless method — drop `wpa_supplicant.conf` in the boot FAT32 partition and let `raspberrypi-net-mods` move it to `/etc/wpa_supplicant/` on first boot — **no longer exists**. The systemd service that did this was removed.

Modern RPi OS uses:
- **cloud-init** for first-boot provisioning (reads from `/boot/firmware/`)
- **NetworkManager** as the network backend
- **netplan** as an intermediate config layer between cloud-init and NM

## 2. Cloud-Init `network-config` Has a Broken WiFi Pipeline

Cloud-init reads `network-config` (netplan v2 YAML) from the boot partition and runs `netplan generate` to create NM keyfiles. Problems found:

- **SSID encoding bug**: Non-ASCII characters (e.g., `ñ`) in SSIDs get mangled into semicolon-separated byte values (`85;110;32;...`) in the generated netplan YAML, which NM may not match correctly.
- **`bringup=False`**: Cloud-init writes the config but explicitly says "Not bringing up newly configured network interfaces."
- **Missing module**: `cc_netplan_nm_patch` (the cloud-init module that patches netplan→NM integration) doesn't exist on the image.
- **One-shot**: `network-config` is only applied on first boot. Subsequent changes require wiping `/var/lib/cloud/`.

**Verdict**: Don't rely on `network-config` for WiFi. It's broken for non-trivial SSIDs and the pipeline has gaps.

## 3. The Reliable Method: Direct NM Connection File

Write a `.nmconnection` keyfile directly to the rootfs partition:

```ini
# /etc/NetworkManager/system-connections/wifi-home.nmconnection
[connection]
id=MyNetwork
type=wifi
autoconnect=true
autoconnect-priority=10

[wifi]
mode=infrastructure
ssid=MyNetwork

[wifi-security]
key-mgmt=wpa-psk
psk=MyPassword

[ipv4]
method=auto

[ipv6]
method=auto
addr-gen-mode=default
```

**Critical**: file must be `chmod 600` and `chown root:root`. NM ignores files with wrong permissions.

Then disable cloud-init network config to prevent conflicts:

```bash
# /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
network: {config: disabled}
```

And remove any leftover netplan WiFi YAML from `/etc/netplan/`.

## 4. The Pi User Account is Locked by Default

Modern RPi OS images ship with user `pi` but the account is **locked** (`!` in `/etc/shadow`). For headless SSH access, you must either:

- Set a password hash directly in `/etc/shadow` via:
  ```bash
  openssl passwd -6 yourpassword
  ```
- Or configure it in `user-data` (cloud-init):
  ```yaml
  users:
  - name: pi
    lock_passwd: false
    passwd: $6$...hash...
    ssh_authorized_keys:
    - ssh-rsa AAAA...
    sudo: ALL=(ALL) NOPASSWD:ALL
  ```
- Or deploy SSH keys directly to `/home/pi/.ssh/authorized_keys` (owned by uid 1000, mode 600/700)

For belt-and-suspenders on a headless setup, do both: set the password in shadow AND deploy the SSH key directly on the rootfs. Don't trust cloud-init alone.

## 5. SSH Must Be Explicitly Enabled

Create an empty file `/boot/ssh` (or `/boot/firmware/ssh`). The `sshswitch.service` checks for this and enables `ssh.service`.

## 6. rfkill Can Silently Block WiFi

Check `/var/lib/systemd/rfkill/` — systemd persists rfkill state across reboots. The WiFi chip file (e.g., `platform-3f300000.mmcnr:wlan` for Pi 3) may contain `1` (blocked).

Fix: write `0` to the file, or from a running system: `rfkill unblock wifi`.

## 7. Verify the Exact SSID

Router-broadcasted SSIDs may differ from what you think. Use the debug log or `nmcli dev wifi list` to see the actual SSID. Common mismatches:
- Router appends band suffix: `MyNetwork` vs `MyNetwork 2.4` vs `MyNetwork 5G`
- Trailing/leading spaces
- Unicode normalization differences

## 8. WPA 4-Way Handshake Failure = Wrong Password

If NM logs show:
```
WPA: 4-Way Handshake failed - pre-shared key may be incorrect
CTRL-EVENT-SSID-TEMP-DISABLED ... reason=WRONG_KEY
```
The password is wrong. Period. Don't look for other causes.

## 9. No Logs by Default — Enable Persistent Journal

RPi OS Trixie ships with **no syslog** and **volatile journald** (logs only in RAM, lost on reboot). For debugging:

```bash
mkdir -p /etc/systemd/journald.conf.d/
cat > /etc/systemd/journald.conf.d/persist.conf << EOF
[Journal]
Storage=persistent
SystemMaxUse=50M
EOF
mkdir -p /var/log/journal
```

## 10. Debug Service for Headless WiFi Troubleshooting

When you can't SSH in and have no monitor, this systemd service dumps diagnostic info to a file you can read by plugging the SD card into another machine:

```ini
# /etc/systemd/system/wifi-debug.service
[Unit]
Description=WiFi debug log
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sleep 30
ExecStart=/bin/bash -c "exec > /var/log/wifi-debug.log 2>&1; \
  echo '=== '$(date)' ==='; \
  rfkill list; \
  ip addr show wlan0; \
  nmcli general status; \
  nmcli con show; \
  nmcli dev status; \
  nmcli dev wifi list 2>&1; \
  ls -la /etc/NetworkManager/system-connections/; \
  ls -la /run/NetworkManager/system-connections/ 2>/dev/null; \
  dmesg | grep -iE 'brcm|wlan|wifi|firmware' | tail -30; \
  journalctl -u NetworkManager --no-pager -n 50 2>/dev/null; \
  journalctl -u wpa_supplicant --no-pager -n 30 2>/dev/null"

[Install]
WantedBy=multi-user.target
```

Enable with: `systemctl enable wifi-debug.service`

Remove after WiFi is working.

---

## Quick Reference: Headless Setup Checklist

1. Flash RPi OS (Bookworm/Trixie) to SD card
2. Mount both partitions (bootfs + rootfs)
3. Create `/boot/ssh` (empty file)
4. Write `/etc/NetworkManager/system-connections/wifi-home.nmconnection` (chmod 600)
5. Create `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg` with `network: {config: disabled}`
6. Set pi password in `/etc/shadow` using `openssl passwd -6`
7. Deploy SSH public key to `/home/pi/.ssh/authorized_keys`
8. Optionally configure `user-data` for hostname, keyboard, packages
9. Check rfkill state files in `/var/lib/systemd/rfkill/` — ensure wlan is `0`
10. Enable persistent journald for future debugging
11. Verify exact SSID from router admin panel (watch for band suffixes)
12. Unmount, boot, wait ~90s, then `ssh pi@raspberrypi.local`
