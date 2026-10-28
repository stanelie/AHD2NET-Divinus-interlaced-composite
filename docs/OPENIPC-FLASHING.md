# Flashing OpenIPC on the converter (GK7205V200, 8 MB NOR)

Runbook for replacing the stock "CAMAPP" firmware with OpenIPC, tailored to
what we found on this board. Read `FIRMWARE-RE.md` and `PTZ-PROTOCOL-stock.md`
first.

## The constraint that picks the method

**The stock U-Boot has no networking** (no `tftp`/`ping`/`loadb`/`loady`;
confirmed via its `help`). So the standard OpenIPC "interrupt U-Boot → tftpboot"
install **does not work as written** on this board. The stock OTA web-upgrade is
signature-checked, so a hand-built image won't flash through it either.

The clean path is **OpenIPC `defib`** using its **BootROM serial handshake**:
the GK7205V200 mask ROM accepts a serial upload *before* U-Boot runs, so defib
pushes an unlocked OpenIPC U-Boot into RAM over the **UART adapter we already
have on COM6** — no network U-Boot, no SPI clip, no open-heart surgery.

## Staging status & Monday steps (2026-10-23)

Everything host-side is **staged and tested up to the handshake**:

- `defib` installed (Python 3.14 venv); gk7205v200 agent **built**:
  `firmware/openipc/agent-gk7205v200.bin` (md5 `8ef7260…`), sources +
  build inputs in `tools/defib-agent/`.
- OpenIPC firmware downloaded + verified: `firmware/openipc/firmware.bin.gk7205v200`
  (kernel+rootfs, uImage@0 / squashfs@0x1e0000; **no U-Boot** — `defib install`
  fetches the matching OpenIPC U-Boot).
- Host can bind UDP 69 **without admin** (Windows), so `defib install`'s TFTP is OK here.

**Finding that gates timing:** a **software / network reboot does NOT open this
chip's serial BootROM download window** — defib sat on "Waiting for bootrom…"
through repeated network-triggered reboots and never caught it (the board just
booted back to stock). The GK7205V200 mask ROM only offers the UART handshake on
a **true cold power-on**. So the flash needs physical access — **do it Monday.**

**Monday, at the device (UART on COM6 @115200):**
```
cd <scratch>/   &&  export DEFIB_AGENT_DIR=<repo>/tools/defib-agent
# 1) validate the handshake (non-destructive): start, then PULL POWER and replug
defib agent upload -c gk7205v200 -p COM6          # should catch bootrom + load agent
defib agent info -p COM6                          # flash id/size readout
# 2) the real install (destructive): start, then cold power-cycle on cue
defib install -c gk7205v200 \
  --firmware <repo>/firmware/openipc/firmware.bin.gk7205v200 \
  -p COM6 --nor-size 8 --host-ip <PC-LAN-IP> --device-ip <free-LAN-IP>
# 3) in the new OpenIPC U-Boot:  setnor8m; saveenv; reset   then  firstboot
```
Recovery if needed: `defib restore` / `flashrom -w firmware/stock/flash.bin`.

## Pre-flight

- **Backup exists and is verified:** `firmware/stock/flash.bin` (full 8 MB, 0
  gaps). This is the restore image. Do not lose it.
- **Hardware:** the same 3.3 V USB-UART on the console pads (TX/RX/GND) at
  115200. For the network-assisted flash step, the board's Ethernet + a TFTP
  server on the PC. Optionally a controllable power outlet (defib can
  power-cycle automatically; otherwise you pull power on cue).
- **Host tool:** `defib` — browser version (Chrome/Edge/Opera, WebSerial) or the
  Python CLI (`pip install` from `github.com/OpenIPC/defib`). CLI is better for
  scripting; the browser tool is easiest for the BootROM handshake.
- **Images:** from the OpenIPC GK7205V200 install generator
  (`openipc.org/cameras/vendors/goke/socs/gk7205v200`) choose **NOR 8 MB
  (5 MB rootfs) — Lite edition** (8 MB only fits Lite). You get an OpenIPC
  U-Boot and the `openipc-gk7205v200-lite-8mb` firmware. defib can also fetch
  these itself.

## Flashing — two defib routes

### Route A — BootROM handshake + install (recommended)

1. Close anything else holding COM6 (our serial scripts).
2. Start defib and select the **BootROM / recovery** flow **before powering the
   board** — it must catch the mask ROM at power-on:
   - CLI: `defib install --soc gk7205v200 ...` (it drives the handshake, loads
     OpenIPC U-Boot to RAM, brings up U-Boot networking, serves the image over
     TFTP, writes it, and CRC32-verifies).
   - Browser: open the defib page, pick the serial port, start, then power the
     board.
3. Power-cycle the board on cue. defib loads the unlocked U-Boot into RAM (flash
   untouched at this point), then flashes OpenIPC U-Boot + firmware.
4. Let it finish and verify (CRC32).

> Serial-only variant: `defib agent flash` writes the image over UART alone (no
> network) via a RAM "agent", if a prebuilt agent for gk7205v200 is available.
> Use it if you can't run a TFTP server.

### Route B — SPI clip fallback (most bulletproof)

If defib can't catch the BootROM: SOIC-8 clip + a **3.3 V** programmer
(`flashrom`, or a *voltage-modded* CH341A — stock CH341A is 5 V and will stress
the 3.3 V chip). Hold the SoC in reset, `flashrom -w openipc-...-8mb.bin`,
verify. Restore with `flashrom -w flash.bin`.

## First U-Boot after flashing

In the new OpenIPC U-Boot, set the NOR layout and boot:

```
setnor8m          # 8 MB partition macro (skipping this can kernel-panic)
saveenv
reset
```

After the first full boot, run once:

```
firstboot         # initializes the overlay
```

## First-boot config — video (BT.656 / CVBS NTSC)

This board feeds the TP9950's **parallel BT.656** into the SoC VI; OpenIPC
drives it through the `bt656` "sensor" profile (same mechanism the stock FW
uses — our dump sets `sensor=bt656`).

```
fw_setenv sensor bt656        # U-Boot env sensor selection
# (reboot)
```

Then confirm majestic loaded the bt656 profile and set NTSC geometry in
`/etc/majestic.yaml`:

```yaml
isp:
  sensorConfig: /etc/sensors/bt656.ini   # the bt656 profile (name per build)
video0:
  size: 720x480                          # NTSC active (PAL would be 720x576)
  fps: 30
```

- The TP9950 auto-detects CVBS/AHD and NTSC/PAL and passes BT.656 through, so
  majestic should receive the already-decoded NTSC field. If the picture is
  rolling/half-height, the `[vi_dev]` BT.656 options in the sensor `.ini`
  (interlace/field, work mode) are the knobs — the **stock TP9950 register
  setup is our reference** (in `xm_vi.ko` / the dump).
- Success = a live picture in the majestic stream (the camera is already
  connected and was decoding CVBS NTSC on stock).

## First-boot config — RS-485 PTZ (/dev/ttyAMA1)

From the RE (`PTZ-PROTOCOL-stock.md`): RS-485 = SoC **UART2 → `/dev/ttyAMA1`**,
**19200 8N1**, TX(DI)=GPIO13 @ `0x112c0074`, RX(RO)=GPIO12 @ `0x112c0070`,
DE=GPIO54 (UART2_RTS).

1. **Mux the UART pads** (put in a startup script, e.g. `/etc/init.d/` or via
   OpenIPC's sys_config, so it runs every boot):

   ```
   devmem 0x112c0070 32 2     # RS485_RO -> UART2 RXD
   devmem 0x112c0074 32 2     # RS485_DI -> UART2 TXD
   ```

   (These are exactly the values the stock firmware writes — live-verified.)

2. **Direction (DE) on GPIO54:** half-duplex, so DE must be asserted only during
   TX. DE is the *driver-enable* (direction) line — **not** a polarity control.
   Two options:
   - Kernel PL011 RS-485 mode with RTS-as-DE (UART2_RTS == GPIO54), if the
     driver supports `TIOCSRS485` here; or
   - a GPIO toggle around each write in our actuator (assert before TX, drain
     with `tcdrain`, deassert) — the safe default on this 4.9 kernel.

   **A/B polarity:** cannot be flipped in software on this path — the PL011 has
   no TX/RX invert bit, so the only software inversion would mean a GPIO
   bit-bang (which we're avoiding). Resolve polarity **physically**: swapping
   A/B is harmless (differential pair), so if the camera won't decode, swap the
   two wires. Don't confuse this with the stock `swap_h/v/z` config, which are
   pan/tilt/zoom *direction* reversals, not wiring. Because the camera ignores
   Pelco, confirm polarity with a scope on A/B, or by trying once with the
   Panasonic actuator in place and swapping if there's no movement.

3. **Prove the serial path first with the built-in Pelco driver** (reproduces
   stock behaviour under OpenIPC):

   ```yaml
   # /etc/majestic.yaml  (or majestic-af ptz block, per build)
   ptz:
     enabled: true
     actuator: pelco-d        # or pelco-xm, whichever the build ships
     port: /dev/ttyAMA1
     baud: 19200
     address: 1
   ```

   Drive a move from the WebUI/ONVIF and scope the A/B pair (or watch the
   transceiver). The camera **won't move** (it's Panasonic, not Pelco) — that's
   expected. Valid frames on the wire = the whole chain works.

4. **Then swap in the Panasonic actuator** (the real deliverable): a new
   actuator behind majestic-af's `actuator.h` vtable that opens `/dev/ttyAMA1`
   @ 19200 8N1, toggles DE (GPIO54) around TX, and emits Panasonic frames
   instead of Pelco. Set `ptz.actuator: panasonic`.
   **End-to-end success = the camera physically moves.** (It is connected now.)

## Recovery

If anything goes wrong, restore the verified stock image:

- defib: `defib restore` (or `defib agent flash firmware=flash.bin`) over serial.
- SPI clip: `flashrom -w firmware/stock/flash.bin`.

Because the BootROM handshake loads U-Boot to **RAM**, a failed `install` leaves
the existing flash intact until the write step — low risk of a hard brick, and
the clip is always the ultimate backstop.

## Open items carried into bring-up

- Exact majestic `bt656` profile name / NTSC `[vi_dev]` tuning (verify on first
  boot; stock regs are the reference).
- Whether `TIOCSRS485`/RTS-DE works on this PL011, else GPIO54 toggle.
- The Panasonic frame format itself (the one hard dependency that no amount of
  converter work removes) — pin down from the Panasonic protocol PDFs in
  `docs/reference/` or a capture from a Panasonic controller.
