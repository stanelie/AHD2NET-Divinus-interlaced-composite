# Panasonic actuator for majestic-af

`act_panasonic.c` is a 4th [majestic-af](https://github.com/OpenIPC/majestic-af)
Actuator that drives a **Panasonic WV-CS85x** dome over RS-485 using the
Panasonic CCVE **conventional** ASCII protocol (see `docs/PANASONIC-PROTOCOL.md`).
It replaces the need for the camera to speak Pelco.

## Integrate (two edits + one source line)

1. Copy `act_panasonic.c` into `majestic-af/src/`.
2. `CMakeLists.txt` — add it to the sources list:
   ```cmake
   src/act_uart.c
   src/act_panasonic.c      # <-- add
   ```
3. `src/actuator.c` — declare it and add a row to `choices[]`:
   ```c
   extern const Actuator act_panasonic;   // src/act_panasonic.c
   ...
   static const struct { ... } choices[] = {
       {{"pelco-xm", "XiongMai lens MCU (UART)"}, &act_uart},
       {{"pelco-d",  "Pelco-D (UART)"},           &act_uart},
       {{"panasonic","Panasonic WV-CS85x (CCVE, UART)"}, &act_panasonic},  // <-- add
       ...
   };
   ```
   The WebUI dropdown picks it up automatically (it reads the list from the
   `schema` command).

Build majestic-af against the OpenIPC/majestic SDK as usual (toolchain file in
its `CMakeLists.txt`), and drop the resulting `majestic-af.so` on the camera.

## Build — cross-compiled & verified ✓

The actuator **compiles and links** into `majestic-af.so` for ARM. Verified
2026-10-23 with an `arm-linux-musleabihf` gcc 11.2 (`build-crosscheck.sh`):

```
gcc exit 0 — majestic-af.so: ELF 32-bit LSB shared object, ARM, EABI5
nm: 0001ee90 D act_panasonic          # actuator present
undefined symbols = HAL seams only (config_get_*, log_log, sdk_*) + libc
```

- Only warnings were the same POSIX-implicit ones the stock `act_uart.c`
  produces (resolved by the `-std=gnu99` dialect CMake uses).
- `build/majestic-af.so.musleabihf-testbuild` is that artifact — a **build
  check, not deployable**: it was built hard-float (`musleabihf`) and the
  OpenIPC gk7205v200 target is `arm-openipc-linux-musleabi` (softfp). Build the
  **deployable** `.so` with OpenIPC's own toolchain + the repo's CMake:
  ```sh
  cmake -Bbuild -DCMAKE_TOOLCHAIN_FILE=<majestic>/tools/cmake/toolchains/<cc>.cmake
  cmake --build build         # -> majestic-af.so
  ```
  (best done in the OpenIPC build env). The source is proven correct regardless.

## Configure (`/etc/majestic.yaml`)

```yaml
ptz:
  enabled: true
  actuator: panasonic
  port: /dev/ttyAMA1     # SoC UART2 (see docs/PTZ-PROTOCOL-stock.md)
  baud: 19200
  address: 1             # CCVE unit address = the camera's DIP unit number (1..96)
```

Also set the UART2 pinmux every boot (the SoC powers up with these pads as
GPIO) — see `src/openipc/S96rs485mux`.

## What it implements

- ASCII CCVE frames: `STX [AD<nn>;] GC<N>:<cmd..> ETX`, no checksum.
- Pan/tilt (GCF, 2 cmds, 2.2 s timeout → motion.c already repeats): direction on
  the 3×3 nibble grid, pan/tilt speed 0–7 (mapped from majestic's 0–63).
- Zoom/focus (GC7): tele/wide/far/near/stop.
- `PTZ_STOP`: stops pan/tilt and lens together.
- Half-duplex DE on **GPIO54** (UART2_RTS) via `TIOCSRS485` (RTS-as-DE); logs a
  warning and you fall back to a GPIO54 toggle if the PL011 driver ignores it.
- No magnification reader (`fd()` = -1): the CS854B answers status *requests*
  rather than streaming a zoom ratio.

## Bench verification (ground truth = the camera moves)

Not yet tested against the camera. On the bench confirm, in order:
1. Pinmux + wiring: drive a move, scope the A/B pair for the ASCII frame.
2. Polarity: if the frame is on the wire but the camera ignores it, **swap A/B**
   (harmless) — the PL011 can't invert in software.
3. Protocol: if still nothing, the camera may want the **new** protocol — just
   set `ptz.actuator: panasonic-new` and restart majestic (no rebuild; both
   variants are built in). The CCVE conventional baseline covers the whole
   WV-CS/CW dome family (CS600/650 … CS950/CW9xx), so it's the likely one.
4. Speed/feel: tune the 0–63 → 0–7 (conv) / 0–F (new) mapping.

## Variants (both built in; pick with `ptz.actuator`)

| `ptz.actuator` | protocol | when |
|---|---|---|
| `panasonic` | CCVE **conventional** | default; widest WV-dome coverage |
| `panasonic-new` | Panasonic **new** protocol | faster-PTZ controllers; try if conventional is silent |

The camera is unmarked, so this lets the bench flip between them in a restart.
(An AW-convertible fallback is documented in `docs/PANASONIC-PROTOCOL.md` but not
implemented — a WV dome is far more likely.)
