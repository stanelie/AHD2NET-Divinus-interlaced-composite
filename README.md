# analog-ptz-bridge

Making a **Panasonic WV-CS854B** analog PTZ dome controllable over IP, through a
cheap **AHD/CVBS-to-IP converter** (Goke GK7205V200, XiongMai "CAMAPP"
firmware) whose RS-485 output only speaks Pelco-D/P.

## The problem in one paragraph

The WV-CS854B is a Panasonic broadcast/security PTZ whose RS-485 control
understands **only Panasonic's own protocol** — it has no Pelco mode we can
reach (verified against the manual and confirmed on the unit). The IP converter
we are using drives its RS-485 port with **Pelco-D / Pelco-P only** (confirmed:
the firmware's protocol list has exactly those two, and the backend rejects any
other value). So out of the box the converter and the camera cannot talk. This
project bridges that gap.

## Hardware

| | |
|---|---|
| Camera | Panasonic WV-CS854B, composite **NTSC**, Panasonic-protocol RS-485 PTZ |
| Converter SoC | **Goke GK7205V200** (`chip=gk7205ev200`) |
| Converter board | XiongMai (`xm72050200` U-Boot), 64 MiB DRAM |
| Flash | **8 MB** SPI NOR, FM25Q64 (`0xa1 0x40 0x17`) |
| Video decoder | TP9950 (decodes the camera's CVBS NTSC — confirmed working) |
| Converter stock FW | custom "CAMAPP" v2.0.25, Linux 4.9.37, squashfs root + jffs2 `usr` |
| RS-485 on converter | present on a connector; driven by **GPIO bit-bang** (see findings) |

## Options being evaluated

1. **Flash OpenIPC** on the converter and write a `panasonic` PTZ actuator for
   `majestic-af` (its driver model already has `pelco-d`/`pelco-xm`). Converter
   emits Panasonic directly; one box.
2. **Keep stock firmware** and add an **ESP32 Pelco→Panasonic translator**
   between the converter's RS-485 output and the camera. No converter firmware
   work, but an extra box.

Either way the hard dependency is the **Panasonic PTZ byte format** — see
`docs/reference/` for the Panasonic protocol specs collected so far.

## Video over IP (working)

Separate from the PTZ problem, the converter now serves the camera's NTSC
composite as **full-resolution 640×480 colour** over RTSP, an MJPEG web preview,
and an EpocCam-compatible **ExMachino** sender — all at once, on the stock
kernel, starting at boot. The GK7205V200 can't hardware-weave an interlaced
BT.656 source, so the two 240-line NTSC fields are interleaved and downscaled in
software (low latency) inside a modified OpenIPC/divinus.

- **Default login:** SSH as `root`, password `patatepatate` — change it with
  `passwd` on anything not on a trusted network.
- **Build it from scratch:** [`BUILD.md`](BUILD.md)
- **How it works / gotchas:** [`divinus/RUN.md`](divinus/RUN.md)
- **Full buildable source:** [`divinus-src/`](divinus-src/)

## Repo layout

```
firmware/
  stock/
    flash.bin            full verified 8 MB dump (serial md.b, 0 gaps)
    partitions/          carved: boot, env, kernel(uImage), rootfs(squashfs), usr(jffs2)
    rootfs/              extracted squashfs root filesystem
    usr_jffs2/           extracted jffs2 /usr (contains camapp, web UI, config, passwd)
    res/                 ptz.ko carved from camapp's embedded res.tar
  analysis/
    ptz.ko.disasm        annotated Thumb-2 disassembly of the PTZ driver
    camapp.strings       strings of the main app binary
    kernel.strings
docs/
  reference/             Panasonic protocol PDFs + extracted text, WV-CS854B manual
  FIRMWARE-RE.md         full reverse-engineering writeup (read this)
tools/                   serial capture / dump / carve / unpack / analysis scripts
esp32/                   (reserved) ESP32 translator firmware if option 2 is taken
divinus-src/             full buildable OpenIPC/divinus source with the video mods
divinus/                 device overlay (config, init, sensor ini), RUN.md, built binary
```

## Status

- [x] Confirmed camera is Panasonic-protocol only (no reachable Pelco)
- [x] Confirmed converter firmware offers only Pelco-D / Pelco-P
- [x] Confirmed converter decodes the camera's CVBS NTSC video
- [x] Full 8 MB stock firmware dumped over serial and **verified (0 gaps)**
- [x] Firmware unpacked; **PTZ control architecture reverse-engineered**
- [x] **RS-485 path pinned down**: SoC UART2 → `/dev/ttyAMA1`, 19200 8N1,
      TX/RX on IOMUX `0x112c0074`/`0x70`, DE=GPIO54 (live-verified + OpenIPC wiki)
- [x] **Stock Pelco-P command set captured & decoded** (live PTZ capture)
- [x] **Panasonic WV-CS85x CCVE protocol decoded** → `docs/PANASONIC-PROTOCOL.md`
- [x] **Panasonic majestic-af actuator written** → `src/majestic-af/act_panasonic.c`
- [x] OpenIPC flash fully **staged** (defib + built agent + image) → `docs/OPENIPC-FLASHING.md`
- [ ] **Flash OpenIPC** — blocked on a physical cold power-cycle (BootROM needs it;
      a software reboot does not open the window). Turnkey, waiting for bench access.
- [ ] Bench-verify the actuator (ground truth = the camera moves): protocol choice,
      A/B polarity, speed feel

See **[docs/FIRMWARE-RE.md](docs/FIRMWARE-RE.md)** (firmware internals),
**[docs/PTZ-PROTOCOL-stock.md](docs/PTZ-PROTOCOL-stock.md)** (the UART/pin resolution),
**[docs/PANASONIC-PROTOCOL.md](docs/PANASONIC-PROTOCOL.md)** (the target protocol), and
**[docs/OPENIPC-FLASHING.md](docs/OPENIPC-FLASHING.md)** (the flash runbook).

> Note: this repo contains extracted vendor firmware (busybox, camapp, ptz.ko,
> etc.). Keep it **private**.
