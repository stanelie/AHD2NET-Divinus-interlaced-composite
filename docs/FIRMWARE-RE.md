# Converter firmware — reverse engineering notes

Target: the AHD/CVBS→IP converter, **Goke GK7205V200**, XiongMai board, custom
"CAMAPP" firmware. All findings below are from the verified 8 MB dump in
`firmware/stock/flash.bin`.

## 1. How the dump was taken

No network in the stock U-Boot (no `tftp`/`ping`/`loadb`), and the Linux console
is login-gated, so the dump was done from the **U-Boot prompt over the serial
console** (CP210x @ 115200 8N1 — the board's U-Boot baud table is capped at
115200; 230400/460800/921600 are all rejected):

```
sf probe 0
sf read 0x42000000 0x0 0x800000      # whole chip -> RAM
md.b 0x42000000 0x800000             # stream hex over serial (~60 min)
```

The hex stream was captured and reassembled (`tools/parse_dump.py`). Result:
**524,288 lines, 8,388,608 / 8,388,608 bytes, 0 gaps.** Byte-exact.

## 2. Flash layout

`mtdparts=sfc:128K(boot),64K(env),1792K(kernel),3M(rootfs),-(usr)`

| # | Partition | Offset | Size | Contents |
|---|---|---|---|---|
| 0 | boot  | 0x000000 | 128 K | U-Boot 2020.01 (`xm72050200`) |
| 1 | env   | 0x020000 | 64 K  | U-Boot env (CRC + key=val) |
| 2 | kernel| 0x030000 | 1792 K| uImage, Linux 4.9.37 |
| 3 | rootfs| 0x1F0000 | 3 M   | **squashfs 4.0, xz**, read-only |
| 4 | usr   | 0x4F0000 | 3.06 M| **jffs2**, writable — app, web UI, config, passwd |

Boot flow: `bootcmd = sf probe 0; xmediaapp; sf read 0x41000000 0x30000 0x200000; bootm`.
`/etc/init.d/S99camapp` mounts jffs2 `mtdblock4` at `/usr` and runs
`/usr/sbin/camapp`.

## 3. UARTs

From `rootfs/etc/init.d/S00devs`:

```
mknod /dev/ttyAMA0 c 204 64     # console  (U-Boot + Linux console, bootargs console=ttyAMA0)
mknod /dev/ttyAMA1 c 204 65     # second UART
mknod /dev/ttyS000 c 204 64     # alias of console
```

`ttyAMA0` is the console. **`ttyAMA1` is the only spare hardware UART** — but
note section 4: the stock firmware does **not** use a hardware UART for PTZ at
all.

## 4. PTZ / RS-485 control architecture  ← key finding

> **UPDATE (confirmed by a verbose live boot, `firmware/analysis/verbose_boot.log`):**
> In our configuration (`[motor] type=2`, Pelco), RS-485 is driven by a
> **hardware UART**, *not* the GPIO bit-bang. The bit-bang module `ptz.ko`
> **does not load at all** in this mode (no `moto`/`gpio_request`/`GPIO PTZ`
> lines in the boot log). Instead camapp's **`ptz_uart.c`** emits the Pelco
> stream, and the log shows the actual bytes on the wire:
>
> ```
> ptz_uart.c:191  ptz_uart_set to UART0 failed!!!
> ptz_uart.c:198  ptz_uart_set to UART1 failed!!!
> ptz_uart.c:212  =========>>>>>>> [A0][01][00][07][00][54][AF][5D]
> ```
>
> `[A0 01 .. AF cksum]` is a valid **Pelco-P** frame, **address 1**, at the
> configured baud. So `ptz.ko` (below) is the *stepper-motor* path (other board
> variants / `type` values); it is not used for RS-485 Pelco here.
>
> **Implication for OpenIPC:** we can use a standard tty-based PTZ driver on
> `/dev/ttyAMAx` — no software-UART/bit-bang actuator needed.
>
> **RESOLVED (root shell + OpenIPC wiki) — see `docs/PTZ-PROTOCOL-stock.md`:**
> RS-485 is SoC **UART2**, **`/dev/ttyAMA1` under OpenIPC**, **19200 8N1**.
> TX(RS485_DI)=GPIO13 @ IOMUX `0x112c0074`=fn2; RX(RS485_RO)=GPIO12 @
> `0x112c0070`=fn2; DE=GPIO54 (UART2_RTS). Live-verified: camapp holds
> `/dev/ttyAMA1` open, its PL011 IBRD/FBRD = 78/8 → 19200 8N1, and the IOMUX
> regs read `0x1002`. Matches the OpenIPC GPIO wiki's tested GK7205V200 RS-485
> recipe exactly.

### (The GPIO bit-bang path — used for stepper variants, not our Pelco mode)

The firmware *also* contains a GPIO bit-bang PTZ path (used when the pan/tilt is
a local stepper motor rather than an RS-485 head):

- **`/usr/sbin/camapp`** (1.44 MB static ARM ELF) is the whole application:
  video, the web server + embedded web UI, ONVIF, and PTZ. It carries an
  embedded `res.tar` (640 KB) that it unpacks to `/tmp/res/` at boot, which
  contains **`res/drv/ptz.ko`** (extracted to `firmware/stock/res/ptz.ko`).
- **`ptz.ko`** — "GPIO PTZ driver" (`description=GPIO PTZ driver`,
  `author=Fork`, `vermagic=4.9.37`). It:
  - exposes a char device with `ptz_fops` / `ptz_ioctl` / `ptz_open`;
  - drives pins with the GPIO-descriptor API: `gpio_request`,
    `gpio_to_desc`, `gpiod_direction_output_raw`, `gpiod_set_raw_value`;
  - times the bit-bang with **hrtimers** (`hrtmer0_hander`, `hrtmer1_hander`
    in its `.rodata`) — i.e. a software UART / software-timed Pelco on GPIO.
- **The GPIO pin numbers are NOT in `ptz.ko`.** Its init does
  `arm_copy_from_user` of a **76-byte (0x4c) config struct** into a `.bss`
  object (`.LANCHOR0`), then loops requesting the GPIOs named in that struct
  (4 entries at offset 0, plus one at +0x20). So **camapp passes the pin
  numbers down via ioctl**; the integers are compile-time constants inside
  `camapp`, selected by the motor `type`.
- **The pins are not in the config files either** (checked
  `usr/etc/syscfg/sys.ini`, `usr/etc/iotcfg/sys.ini`).

### PTZ runtime config — `usr/etc/syscfg/sys.ini` / `iotcfg/sys.ini`

```
[motor]
type   = 2            # selects the GPIO/bit-bang Pelco motor driver in camapp
speed  = 20
uart_baud     = 19200 # (iotcfg) / 2400 (syscfg default)  -> the Baud field in the web UI
uart_addr     = 1     # Pelco device address
uart_protocol = 1     # 0 = PELCO-D, 1 = PELCO-P
swap_h/v/z, step_*, home_*, angle_h=355, angle_v=180
```

These map 1:1 to the web UI PTZ tab (Baud / Protocol / Address / Speed / Swap
H,V,Z) and to the JSON API `GET/POST /api/ptz/config`
(`{baud, protocol, addr, speed, swaph, swapv, swapz}`) and `POST
/api/ptz/action {direction}`.

### What this means for our project

- The converter produces Pelco by **bit-banging a GPIO into the RS-485
  transceiver's DI**, timed in software. There is a spare hardware UART
  (`ttyAMA1`) we could use instead under OpenIPC.
- **Open item — exact pin numbers.** Two reliable ways to get them:
  1. **Runtime read:** boot stock firmware normally (so camapp loads ptz.ko),
     get a root shell, then `cat /sys/kernel/debug/gpio` — it lists every
     requested GPIO with the driver's label and pin number. (Needs login, see
     §5.)
  2. **Static:** continue disassembling `camapp` to the `ioctl` call site that
     fills the 76-byte struct for `type=2`. More work; self-contained.
  A quick multimeter check (which transceiver DI pin is toggling while driving
  PTZ, traced back to a SoC ball) cross-checks either.

## 5. Credentials (own-device recovery)

`usr/etc/passwd`:

```
root:Ca/laHEf4BTPI:0:0::/root:/bin/sh
```

- `Ca/laHEf4BTPI` is a **traditional DES crypt** hash (13 chars, salt `Ca`).
  Not a known IoT default and not ≤4 chars (checked a default-password list
  plus a short brute force). Crack it on a real machine:

  ```
  hashcat -m 1500 -a 3 hash.txt ?a?a?a?a?a?a?a?a      # descrypt, up to 8 chars
  # or: john --format=descrypt hash.txt
  ```

- **Shell without the password (recovery):** from the serial U-Boot prompt,
  append `init=/bin/sh` to the kernel bootargs for a one-shot boot:

  ```
  setenv bootargs <existing bootargs> init=/bin/sh       # do NOT saveenv
  boot
  ```

  That drops to a root shell (no password). To then inspect PTZ GPIOs you must
  start the app path (mount `/usr`, `insmod` ptz.ko / run camapp) since under
  `init=/bin/sh` camapp did not run. `passwd` here can also set a known root
  password persistently (rootfs is squashfs/RO, but `/usr` passwd is jffs2/RW).

> The web UI login is separate (HTTP Basic, `admin` / `admin`), served by
> camapp; API auth is Basic over `/api/*`.

## 6. Tooling

Scripts in `tools/` (Windows / Git Bash + the project venv Python):

| script | purpose |
|---|---|
| `serial_listen.ps1` | passive serial capture (boot log) |
| `uboot_cmd.ps1` | send U-Boot commands, read replies |
| `dump_flash.ps1` | `sf read` + `md.b` full-flash serial dump |
| `parse_dump.py` | reassemble md.b hex → binary, verify gaps |
| `carve.py` | split flash.bin into partitions |
| `unsq.py` / `unjffs.py` | extract squashfs / jffs2 |
| `extract_ko.py` | carve ptz.ko from camapp's embedded res.tar |
| `ptz_full.py` / `ptz_pins.py` | disassemble + analyze ptz.ko |
| `crack2.py` | dictionary/brute attempt on the DES hash |
