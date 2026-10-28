# Building the working video firmware from scratch

The "working firmware" is an **OpenIPC** base plus a **custom `divinus` binary**
that does the software NTSC field-weave (two 240-line fields → 640×480 colour),
served over RTSP + MJPEG + an ExMachino sender, plus a small overlay (config +
init script). This file is the end-to-end recipe. Architecture, gotchas and the
per-register detail live in [`divinus/RUN.md`](divinus/RUN.md).

## What you need

- A Linux build host (a WSL2 Ubuntu shell is what this was built on).
- `make`, and `wget` **or** `curl`, and `tar`.
- ~400 MB free: `build.sh` downloads the HiSilicon cross-toolchain on first run.
- The target device: an AHD2NET-class converter, **Goke GK7205V200 + TP9950**,
  running OpenIPC (see "Base firmware" below).

## 1. Build the divinus binary

The complete, buildable source (OpenIPC/divinus with all the changes for this
project) is vendored in [`divinus-src/`](divinus-src/). From a Linux/WSL shell:

```sh
cd divinus-src
./build.sh hisi-v4
```

`build.sh` fetches `toolchain.hisilicon-hi3516ev200` from the OpenIPC releases
into `divinus-src/toolchain/` (first run only), then compiles. The result is:

```
divinus-src/divinus      # ARM binary, ~400 KB
```

Note: the startup banner shows a git revision baked in at compile time
(`-DGIT_REV`, from `src/Makefile`). This vendored tree has no `.git`, so the
banner shows an empty/`-mod` revision — cosmetic only; the binary is otherwise
identical to the deployed one. (The convenience copies of just the changed
files in [`divinus/`](divinus/) are a diff reference; `divinus-src/` is what you
actually build.)

## 2. Base firmware (OpenIPC)

Flash OpenIPC onto the converter. The image and split used here are in
[`firmware/openipc/`](firmware/openipc/); the flashing runbook (defib / BootROM
over UART — a software reboot does **not** open the window) is in
[`docs/OPENIPC-FLASHING.md`](docs/OPENIPC-FLASHING.md). The stock vendor image
in `firmware/stock/` is only for restoring the device to factory, not for this
build.

## 3. Install divinus + overlay onto the device

Copy the binary and the overlay (these are the persistent, reboot-surviving
pieces — see `divinus/RUN.md` for the full list and why each matters):

| On the device | From this repo |
|---|---|
| `/usr/bin/divinus` | `divinus-src/divinus` (what you just built) |
| `/etc/divinus.yaml` | `divinus/divinus_live.yaml` |
| `/etc/bt656_ntsc.ini` | `divinus/bt656_prog.ini` |
| `/etc/init.d/S96divinus` | `divinus/S96divinus` (boot start + respawn supervisor) |

Also whiteout `S95majestic` in the overlay so majestic does not autostart and
hold ports 80/554. The stock `/rom` `gk7205v200_vi.ko` is used as-is (no kernel
patch — progressive capture + software weave needs none).

## 4. Deploy / update an already-running device

Because the init script supervises divinus (respawns it on exit/crash), stop and
start through the script rather than `kill`:

```sh
/etc/init.d/S96divinus stop        # stops the supervisor, then divinus
#   ... replace /usr/bin/divinus ...
/etc/init.d/S96divinus start
```

The overlay (jffs2) is tiny (~768 KB). The old binary's blocks only free once
the process has fully exited, so always `stop` before overwriting.

## 5. Verify

- RTSP: `rtsp://<device-ip>:554/` (use TCP transport in VLC)
- Web preview + MJPEG: `http://<device-ip>/`
- ExMachino viewer: it discovers the device over mDNS (`_epoccam._tcp`, port
  5054), or connect to `<device-ip>:5054` directly.

A clean boot: stock kernel loads VI → `S96divinus` starts divinus (under the
supervisor) → the weave thread applies the TP9950 NTSC registers and begins
weaving → 640×480 colour on all three services.
