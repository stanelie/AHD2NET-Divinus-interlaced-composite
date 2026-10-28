# Stock converter — live PTZ serial output (decoded)

Captured on the serial console (`loglevel=8`) while driving PTZ via the web API
`POST /api/ptz/action`. The app (`ptz_uart.c:212`) logs every frame it emits.
Raw capture: `firmware/analysis/ptz_move.log`.

## Protocol: Pelco-P, address 1

Frame = `A0  ADDR  CMD1  CMD2  DATA1(pan spd)  DATA2(tilt spd)  AF  BCC`
where **BCC = XOR of the 7 preceding bytes** (STX..ETX). Verified on every frame.

Config in use: `uart_protocol=1` (Pelco-P), `uart_addr=1`, `speed=20 (0x14)`.

| Web/ONVIF cmd | Frame (hex) | CMD2 bit | meaning |
|---|---|---|---|
| UP       | `A0 01 00 08 00 14 AF 12` | 0x08 | tilt up, tilt speed 0x14 |
| DOWN     | `A0 01 00 10 00 14 AF 0A` | 0x10 | tilt down |
| LEFT     | `A0 01 00 04 14 00 AF 1E` | 0x04 | pan left, pan speed 0x14 |
| RIGHT    | `A0 01 00 02 14 00 AF 18` | 0x02 | pan right |
| ZOOM_IN  | `A0 01 00 20 00 00 AF 2E` | 0x20 | zoom tele |
| STOP     | `A0 01 00 00 00 00 AF 0E` | 0x00 | all stop |

CMD2 bit map (standard Pelco-P): `0x02`=right, `0x04`=left, `0x08`=up,
`0x10`=down, `0x20`=zoom tele, `0x40`=zoom wide. CMD1 carries focus/iris/preset
bits (not exercised here). This is the exact command set our OpenIPC Panasonic
actuator must translate *from* (ONVIF/majestic → Panasonic), so it's a useful
reference even though the camera itself ignores Pelco.

## UART identity — RESOLVED (root-shell + OpenIPC wiki)

Via a root shell (`init=/bin/sh`, no password needed), ran the normal init so
camapp came up fully, then read its open FDs and the live hardware:

- `ls -l /proc/$(pidof camapp)/fd` → camapp holds **`/dev/ttyAMA1`** and
  `/dev/ttyAMA2` open (plus the full video pipeline). RS-485 is a real UART.
- **PL011 baud registers** (UARTCLK ≈ 24 MHz, derived from the 115200 console):
  | UART | base | IBRD | FBRD | → baud | LCRH | → format |
  |---|---|---|---|---|---|---|
  | ttyAMA0 (console) | 0x12040000 | 13 | 1 | 115200 | 0x70 | 8N1 |
  | ttyAMA1 | 0x12041000 | **78** | **8** | **19200** | 0x70 | **8N1** |
  | ttyAMA2 | 0x12042000 | 78 | 8 | 19200 | 0x70 | 8N1 |
- **Live IOMUX** (`devmem`): `0x112c0070 = 0x1002`, `0x112c0074 = 0x1002`
  (function 2).

Cross-referenced with the OpenIPC GPIO wiki (`en/gpio-settings.md`, "Tested on
GK7205V200"), which labels these exact registers:

| Signal | GPIO/pad | IOMUX reg | mux fn | Linux dev (OpenIPC) |
|---|---|---|---|---|
| UART2_RXD / **RS485_RO** (rx) | 12 | `0x112c0070` | 2 | `/dev/ttyAMA1` |
| UART2_TXD / **RS485_DI** (tx) | 13 | `0x112c0074` | 2 | `/dev/ttyAMA1` |
| UART2_RTS / **RS485_DE** (dir) | 54 | (pad 54) | — | — |

**Answer:** RS-485 is the SoC **UART2** block — TX(DI)=GPIO13 @ `0x112c0074`,
RX(RO)=GPIO12 @ `0x112c0070`, direction(DE)=GPIO54 (UART2_RTS) — which under
**OpenIPC is `/dev/ttyAMA1`**, at **19200 8N1**. Our stock dump already drives
exactly these pads (live-verified), and the OpenIPC wiki documents the same
recipe, so it is not board-guesswork.

(The app's `ptz_uart_set to UART0/UART1 failed` messages are camapp's own
internal probe labels; it opens and uses the UART regardless. The HW UART also
means **no software bit-bang is needed** — `ptz.ko` never loaded in this mode.)

### OpenIPC bring-up recipe for RS-485 PTZ

```
devmem 0x112c0070 32 2      # RS485_RO  -> UART2 RXD
devmem 0x112c0074 32 2      # RS485_DI  -> UART2 TXD
# DE/direction on GPIO54 (UART2_RTS): drive during TX, or use PL011 RS485 mode
```
Then point the PTZ driver at **`/dev/ttyAMA1`, 19200 8N1**. Our Panasonic
actuator opens that tty and asserts DE (GPIO54) around each transmit.
