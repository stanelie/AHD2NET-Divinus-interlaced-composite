# Flash backup — AHD2NET (GK7205V200 + TP9950), OpenIPC + weave pipeline

Full backup of 10.8.1.31 taken after the software-weave pipeline was installed and
made persistent. 8 MB NOR flash. All files are raw partition dumps.

## Files
| file | size | partition | contents |
|---|---|---|---|
| `full_flash_8MB.bin` | 8 MB | whole flash | uboot + env + firmware, concatenated |
| `uboot.bin` | 256 K | mtd0 `u-boot` | bootloader |
| `env.bin` | 64 K | mtd1 `env` | U-Boot environment — **contains the MAC** (ethaddr=5a:d3:7a:2a:47:69) |
| `firmware.bin` | 7.68 M | mtd2 `firmware` | kernel + rootfs (squashfs) + rootfs_data — the whole OS incl. the weave solution |
| `overlay_rootfs_data.bin` | 768 K | mtd5 `rootfs_data` | **only the overlay** = all the changes made here (binary, configs, init script, majestic whiteout) |

## IMPORTANT: the MAC is in `env`
`ethaddr` is stored in the env partition. If you flash `env.bin` (or the full
image) onto a second device, **both devices get the same MAC** → they will
conflict on the same LAN. So for a clone, do **not** restore env — let the new
device keep its own — or set a fresh `ethaddr` on the clone with
`fw_setenv ethaddr <new-mac>`.

## Restoring / cloning to another (identical) device

The new device must be the same hardware (GK7205V200 + TP9950 BT.656) running the
same OpenIPC base. Pick ONE method:

### A. Clone just the changes (recommended, MAC-safe)
The new device already runs stock OpenIPC for this SoC. Copy the overlay, which
carries everything added here, without touching kernel/rootfs/env:
```sh
# on your PC: scp/base64 overlay_rootfs_data.bin to the new device's /tmp, then:
flashcp -v /tmp/overlay_rootfs_data.bin /dev/mtd5
reboot
```
Keeps the device's own MAC. If the base firmware version differs, prefer method C.

### B. Full OS clone (keeps this device's exact kernel+rootfs)
Overwrites kernel+rootfs+overlay on the new device; leaves its env/MAC alone:
```sh
# copy firmware.bin to the new device /tmp (7.68 MB, fits tmpfs), then:
flashcp -v /tmp/firmware.bin /dev/mtd2
reboot
```
Only flash `uboot.bin`/`env.bin` as well if you deliberately want this device's
bootloader/env — and remember the MAC caveat for env.

### C. File-level copy (most portable, version-tolerant)
If you just want the solution on any OpenIPC gk7205v200/bt656 device, skip the
images and copy these (from ../divinus/ in this repo), then `reboot`:
```
/usr/bin/divinus            (the built ARM binary)
/etc/divinus.yaml           (= divinus_live.yaml)
/etc/bt656_ntsc.ini         (= bt656_prog.ini)
/etc/init.d/S96divinus
rm /etc/init.d/S95majestic   # disable majestic autostart (overlay whiteout)
```

### D. Blank / bricked device (needs SERIAL)
Serial (UART) + U-Boot + TFTP is the only path here — interrupt U-Boot on the
console, `tftp` the image to RAM, and write it to flash. This is the ONLY case
where the serial connection is required; for everything above, SSH is enough.

## Restoring THIS device from backup
```sh
flashcp -v /tmp/firmware.bin /dev/mtd2   # OS + solution
flashcp -v /tmp/uboot.bin   /dev/mtd0    # only if bootloader damaged
# env is already correct on this device; only reflash it if you wiped it:
# flashcp -v /tmp/env.bin   /dev/mtd1
```
