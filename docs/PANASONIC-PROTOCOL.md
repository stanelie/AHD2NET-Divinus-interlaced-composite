# Panasonic WV-CS854B PTZ serial protocol (decoded)

Decoded from **"Panasonic CCVE Products — Protocol Information v4.5" (2013)**,
which covers the **WV-CS85x family** (CS950, CS850B, CW860A, CS580 …). Our
**WV-CS854B** is in that family (the CS850 manual covers CS854 too). The other
PDF (`ConvertibleProtocol.pdf`) is the **AW broadcast** series — wrong protocol,
ignore for this camera.

Source text: `docs/reference/Analog_PTZ_Camera_Protocol_Information.txt`.

## Two protocols

The camera supports two, selectable by the DIP "Panasonic protocol" setting /
the connected controller:

- **Conventional** — compatible with CS600/CS650; always available; general
  commands + PTZF. **Use this as the OpenIPC baseline.**
- **New** — faster PTZF, auto-selected only when a new-protocol controller
  (CU161, MP204+CU360) is attached. Cleaner single-command PTZ, but may need the
  camera to be in new-protocol mode.

Both are **ASCII**, ACK-handshaked, **no checksum**. Serial = **19200 8N1**
(our unit), half-duplex RS-485, unit address **01–96** (the DIP unit number).

## Frame

```
STX [ AD<nn> ; ] GC <N> : <cmd> [ : <cmd> ... ] ETX
```
- `STX`=0x02, `ETX`=0x03, all other bytes printable ASCII.
- `AD<nn>;` optional unit-address prefix (`nn`=01–96 for CS cameras, `ZZ`=all).
  Point-to-point (one camera) can omit it.
- `GC` = "Camera Control Command" header.
- `<N>` = **number of commands** packed in this frame (Fig-1):
  `7`=1, `F`=2, `N`=3, `V`=4, `^`=5, `f`=6, `n`=7, `v`=8, `~`=9, `(`=10.
- each `<cmd>` = **7 chars** = `<ddd><t><fff>`:
  - `<ddd>` destination: `002`=camera functions, `202`=receiver (PTZ) functions
  - `<t>` type: `1`=control, `0`=status request, `2`=text data
  - `<fff>` 3-char function code.
- **Answer:** `STX GC7:<ddd><E|D><fff> ETX` (`E`=OK, `D`=NG). Camera repeats the
  answer up to 4× until the host ACKs; a one-way sender can ignore/drain it.

## Conventional PTZF command set  ← what the actuator uses

The low nibble of the function code is a **direction grid** (same idea on both
axes): `4`=stop, and for the two axes `8`/`C` = −/+ (pan L/R, zoom T/W),
`A`/`E` = +/− (tilt U/D, focus Far/Near); diagonals combine them.

### Pan/Tilt — variable speed (`GCF`, 2 commands), timeout 2.2 s (repeat to hold)
```
STX GCF : 20213 6<N> : 2022 <X><Y> 0 ETX
```
`<N>` direction nibble, `<X>`=pan speed 0–7, `<Y>`=tilt speed 0–7:

| dir | `<N>` | function |
|---|---|---|
| STOP          | 4 | `2021364` |
| LEFT          | 8 | `2021368` |
| LEFT + UP     | 9 | `2021369` |
| UP            | A | `202136A` |
| RIGHT + UP    | B | `202136B` |
| RIGHT         | C | `202136C` |
| RIGHT + DOWN  | D | `202136D` |
| DOWN          | E | `202136E` |
| LEFT + DOWN   | F | `202136F` |

e.g. pan-left at speed 4: `STX GCF:2021368:2022400 ETX`;
stop: `STX GC7:2021364 ETX`.

### Zoom/Focus — fixed speed (`GC7`, single command)
Same grid at `20212 2<N>` (zoom on the `8`/`C` axis, focus on `A`/`E`):

| action | function |
|---|---|
| ZOOM TELE               | `2021228` |
| ZOOM WIDE               | `202122C` |
| ZOOM TELE + FOCUS FAR   | `2021229` |
| FOCUS FAR               | `202122A` |
| ZOOM WIDE + FOCUS FAR   | `202122B` |
| ZOOM WIDE + FOCUS NEAR  | `202122D` |
| FOCUS NEAR              | `202122E` |
| ZOOM/FOCUS STOP         | `2021224` |

Variable-speed zoom/focus exist at `20212 6<N>` (+ a speed command) if needed.

### Preset
- Call: `STX GCF:2021400:2022<XY>0 ETX`, `XY`=00→preset 1 … 3F→preset 64.
- Set: start `GC7:2021540`, position with PTZ, done `GC7:2021542`.
- 65–256 and precise use: "Direct Function Command" (doc §4), e.g.
  `GCF:00219F0:0022640`.

## New protocol — single-command PTZ (built into the actuator too)

Faster PTZF, selected by the camera when a new-protocol controller is attached.
One-way, no answer:
```
STX [AD<nn>;] GC7 : 902 <Z><D><P><T> ETX
```
4 nibbles after `902` (resolved from the examples + Fig 3.2/3.3):

- `<Z>` **zoom** = `cont<<3 | dir<<2 | speed(0..3)` — `dir` 0=tele/1=wide,
  `cont` 0=run/1=stop. So **tele**≈`2`/`3`, **wide**≈`6`/`7`, **stop**=`8`.
- `<D>` **PT direction**, Table 3.2: `0`=Null(zoom-only), `1`=STOP, `8`=Left,
  `9`=Left+Up, `A`=Up, `B`=Right+Up, `C`=Right, `D`=Right+Down, `E`=Down,
  `F`=Left+Down.
- `<P>`,`<T>` **pan / tilt speed** 0..F.

Verified against the doc's examples: `GC7:90288F0` = zoom-idle(8) + Left(8) +
pan-max(F) + tilt-0 = **pan-left max**; `GC7:902C8F0` = **pan-right max**;
`GC7:9023000` = zoom-tele(3) + null(0) = **zoom-tele**; `GC7:9028100` =
zoom-stop(8) + PT-stop(1) = **all stop**. Focus has its own `3.3` command, but
conventional focus (`20212x`) works in new mode too (doc §1), so the actuator
uses that. **Still bench-confirm the exact feel; the direction/stop framing is
solid, the speed scaling less so.**

## If it's neither — AW convertible (long shot)

If the camera turns out to be an **AW broadcast** convertible (not a WV dome),
the protocol is different: ASCII verbs wrapped in `STX…ETX`, e.g. `HPL`/`HPR`
(pan L/R), `HTU`/`HTD` (tilt), `HZT`/`HZW` (zoom), `HFF`/`HFN` (focus), with
`O`/`Q`/`D` command classes (see `docs/reference/Panasonic_ConvertibleProtocol_v3.05.txt`).
Not implemented — a WV dome is far more likely — but noted so it's a known path.

## To verify on the bench (Monday) — ground truth is the camera moving

- Which protocol the CS854B actually honors over RS-485 as wired (try
  conventional first; if no motion, try new-protocol `GC7:902…`).
- Whether a unit-address prefix is required (try without first; add `AD01;`).
- Pan/tilt speed range actually accepted (0–7 conv).
- The new-protocol speed-nibble order, if we end up needing it.

All of this is directly testable now that the camera is connected: send a frame,
watch for movement.
