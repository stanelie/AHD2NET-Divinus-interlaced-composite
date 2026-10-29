#!/usr/bin/env python3
"""Flash the AHD2NET divinus image onto a stock converter, keeping its MAC.

The stock firmware keeps the unit's MAC address in /usr/etc/syscfg/ethmac (a
jffs2 file); OpenIPC keeps it as `ethaddr` in the U-Boot environment. Flashing
the image as-is would give every unit the image's MAC. This script:

  1. backs up the unit's current flash over the BootROM serial link (defib),
  2. pulls the original MAC out of that backup,
  3. patches it into a copy of the image's U-Boot environment (CRC fixed up),
  4. flashes the patched copy.

Standard library only; needs `defib` on PATH (see INSTALL.txt). Run it with
flash.cmd, or:  uv run flash_ahd2net.py --port COM6
"""
import argparse
import datetime
import os
import re
import secrets
import shutil
import struct
import subprocess
import sys
import zlib

CHIP = "gk7205v200"
AGENT = "agent-gk7205v200.bin"
IMAGE = "full_flash_8MB.bin"
FLASH_SIZE = 8 * 1024 * 1024
ENV_OFFSET = 0x40000       # u-boot is 256K; env (mtd1) follows, 64K, one copy
ENV_SIZE = 0x10000
HERE = os.path.dirname(os.path.abspath(__file__))


class Fail(Exception):
    pass


# --------------------------------------------------------------------- MAC

def norm_mac(text):
    s = text.strip().replace("-", ":")
    if re.fullmatch(r"[0-9a-fA-F]{12}", s):
        s = ":".join(s[i:i + 2] for i in range(0, 12, 2))
    if not re.fullmatch(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", s):
        raise Fail("not a MAC address: %r" % text)
    s = s.lower()
    if int(s[:2], 16) & 1:
        raise Fail("%s is a multicast address, not a valid unit MAC" % s)
    if s == "00:00:00:00:00:00":
        raise Fail("00:00:00:00:00:00 is not a valid unit MAC")
    return s


def random_mac():
    b = bytearray(secrets.token_bytes(6))
    b[0] = (b[0] & 0xFE) | 0x02          # unicast, locally administered
    return ":".join("%02x" % x for x in b)


# ------------------------------------------------- stock MAC out of a dump

def _jcrc(data):
    # jffs2 uses the raw (non-inverted) crc32_le with a zero seed
    return (zlib.crc32(data, 0xFFFFFFFF) ^ 0xFFFFFFFF) & 0xFFFFFFFF


def _rtime(src, dlen):
    positions = [0] * 256
    dst = bytearray(dlen)
    out = pos = 0
    while out < dlen:
        value = src[pos]
        repeat = src[pos + 1]
        pos += 2
        dst[out] = value
        out += 1
        back = positions[value]
        positions[value] = out
        for _ in range(repeat):
            dst[out] = dst[back]
            out += 1
            back += 1
    return bytes(dst)


def _inflate(compr, data, dsize):
    if compr == 0:
        return data
    if compr == 1:
        return bytes(dsize)
    if compr == 2:
        return _rtime(data, dsize)
    if compr == 6:
        return zlib.decompress(data)
    raise Fail("jffs2 compression type %d not supported" % compr)


def _jffs2_nodes(dump):
    off = 0
    magic = b"\x85\x19"
    while True:
        pos = dump.find(magic, off)
        if pos < 0 or pos + 12 > len(dump):
            return
        if pos % 4:
            off = pos + 1
            continue
        _, ntype, totlen, hcrc = struct.unpack_from("<HHII", dump, pos)
        if 12 <= totlen <= len(dump) - pos and _jcrc(dump[pos:pos + 8]) == hcrc:
            yield pos, ntype, totlen
            off = pos + ((totlen + 3) & ~3)
        else:
            off = pos + 4


def find_stock_mac(dump):
    """Return the MAC stored in the stock firmware's ethmac file, or None."""
    dirents = {}                    # (parent ino, name) -> (version, ino)
    inodes = {}                     # ino -> [(version, offset, dsize, isize, compr, data)]
    for pos, ntype, totlen in _jffs2_nodes(dump):
        if ntype == 0xE001 and totlen >= 40:
            pino, version, ino, _, nsize, _, node_crc, name_crc = \
                struct.unpack_from("<IIIIBB2xII", dump, pos + 12)
            name = bytes(dump[pos + 40:pos + 40 + nsize])
            if _jcrc(dump[pos:pos + 32]) != node_crc or _jcrc(name) != name_crc:
                continue
            key = (pino, name)
            if key not in dirents or version >= dirents[key][0]:
                dirents[key] = (version, ino)
        elif ntype == 0xE002 and totlen >= 68:
            (ino, version, _, _, _, isize, _, _, _, offset, csize, dsize,
             compr, _, _, data_crc, node_crc) = \
                struct.unpack_from("<IIIHHIIIIIIIBBHII", dump, pos + 12)
            data = bytes(dump[pos + 68:pos + 68 + csize])
            if _jcrc(dump[pos:pos + 60]) != node_crc or _jcrc(data) != data_crc:
                continue
            inodes.setdefault(ino, []).append(
                (version, offset, dsize, isize, compr, data))

    name_of = {ino: name for (_, name), (_, ino) in dirents.items() if ino}
    live = [(pino, ino) for (pino, name), (_, ino) in dirents.items()
            if name == b"ethmac" and ino]
    live.sort(key=lambda c: name_of.get(c[0]) != b"syscfg")   # syscfg/ethmac first
    for _, ino in live:
        nodes = sorted(inodes.get(ino, []))
        if not nodes:
            continue
        buf = bytearray(nodes[-1][3])
        try:
            for _, offset, dsize, _, compr, data in nodes:
                raw = _inflate(compr, data, dsize)[:dsize]
                buf[offset:offset + len(raw)] = raw
        except (Fail, zlib.error, IndexError):
            continue
        text = bytes(buf).decode("ascii", "ignore").strip()
        try:
            return norm_mac(text)
        except Fail:
            continue
    return None


# ------------------------------------------------------ U-Boot env patching

def read_env(image):
    blk = bytes(image[ENV_OFFSET:ENV_OFFSET + ENV_SIZE])
    if len(blk) != ENV_SIZE:
        raise Fail("image is too small to contain the U-Boot environment")
    stored = struct.unpack_from("<I", blk, 0)[0]
    data = blk[4:]
    if zlib.crc32(data) & 0xFFFFFFFF != stored:
        raise Fail("U-Boot environment CRC mismatch -- is this the right image?")
    end = data.find(b"\0\0")
    if end < 0:
        raise Fail("U-Boot environment is malformed")
    items = data[:end].split(b"\0")
    fill = data[end + 2] if end + 2 < len(data) else 0xFF
    return items, fill, len(data)


def env_get(image, key):
    prefix = key.encode() + b"="
    for item in read_env(image)[0]:
        if item.startswith(prefix):
            return item[len(prefix):].decode("ascii", "replace")
    return None


def patch_ethaddr(image, mac):
    items, fill, size = read_env(image)
    if not any(i.startswith(b"bootcmd=") for i in items):
        raise Fail("U-Boot environment has no bootcmd -- refusing to patch")
    entry = b"ethaddr=" + mac.encode()
    for n, item in enumerate(items):
        if item.startswith(b"ethaddr="):
            items[n] = entry
            break
    else:
        items.append(entry)
    body = b"\0".join(items) + b"\0\0"
    if len(body) > size:
        raise Fail("U-Boot environment is full")
    data = body + bytes([fill]) * (size - len(body))
    out = bytearray(image)
    out[ENV_OFFSET:ENV_OFFSET + ENV_SIZE] = struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF) + data
    return bytes(out)


def check_patched(original, patched, mac):
    if len(patched) != len(original):
        raise Fail("patched image changed size")
    if env_get(patched, "ethaddr") != mac:
        raise Fail("patched image does not carry %s" % mac)
    if original[:ENV_OFFSET] != patched[:ENV_OFFSET] or \
       original[ENV_OFFSET + ENV_SIZE:] != patched[ENV_OFFSET + ENV_SIZE:]:
        raise Fail("patch touched more than the environment")


# ------------------------------------------------------------------ driver

def ask(args, prompt):
    if args.yes:
        print(prompt + " [--yes]")
        return
    input(prompt + "  Press Enter to continue (Ctrl+C to stop)... ")


# defib has no baud option, and reads at its fixed 921600 baud drop packets on
# some USB-UART setups (it then aborts: "Read packet seq gap"). Its fast baud is
# a module constant looked up at call time, so we run defib's own CLI in-process
# with that constant lowered.
_BAUD_STUB = (
    "import sys\n"
    "import defib.agent.client as c\n"
    "c.DEFAULT_FAST_BAUD = int(sys.argv[1])\n"
    "sys.argv = ['defib'] + sys.argv[2:]\n"
    "from defib.cli.app import main\n"
    "main()\n"
)


def find_defib_python():
    """Python interpreter of the environment defib was installed into, or None."""
    override = os.environ.get("AHD2NET_DEFIB_PYTHON")
    if override:
        return override if os.path.isfile(override) else None
    sub = os.path.join("Scripts", "python.exe") if os.name == "nt" else os.path.join("bin", "python")
    roots = []
    for cmd in (["uv", "tool", "dir"], ["pipx", "environment", "--value", "PIPX_LOCAL_VENVS"]):
        if shutil.which(cmd[0]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                continue
            if out:
                roots.append(out.splitlines()[-1])
    for root in roots:
        cand = os.path.join(root, "defib", sub)
        if os.path.isfile(cand):
            return cand
    return None


def defib(argv, baud=0):
    env = dict(os.environ, DEFIB_AGENT_DIR=HERE)
    exe = shutil.which("defib") or "defib"
    cmd = [exe] + argv
    note = ""
    if baud:
        py = find_defib_python()
        if py:
            cmd = [py, "-c", _BAUD_STUB, str(baud)] + argv
            note = "   [serial speed limited to %d baud]" % baud
        else:
            print("\nnote: could not locate defib's Python environment, so its default "
                  "(faster, less forgiving) serial speed will be used.")
    print("\n> defib " + " ".join(argv) + note)
    rc = subprocess.run(cmd, env=env).returncode
    if rc:
        raise Fail("defib %s failed (exit %d)" % (" ".join(argv[:2]), rc))


def main():
    ap = argparse.ArgumentParser(
        description="Flash a stock AHD2NET converter, preserving its MAC address.")
    ap.add_argument("--port", help="serial port, e.g. COM6 or /dev/ttyUSB0")
    ap.add_argument("--image", default=os.path.join(HERE, IMAGE),
                    help="image to flash (default: %s next to this script)" % IMAGE)
    ap.add_argument("--mac", help="use this MAC instead of reading it from the unit")
    ap.add_argument("--random-mac", action="store_true",
                    help="if the original MAC cannot be found, make up a unique one")
    ap.add_argument("--from-backup", metavar="FILE",
                    help="read the MAC from an existing 8 MB dump instead of backing up")
    ap.add_argument("--skip-backup", action="store_true",
                    help="do not back up the unit (needs --mac); NOT recommended")
    ap.add_argument("--no-flash", action="store_true",
                    help="only build the patched image, do not touch hardware")
    ap.add_argument("--read-baud", type=int, default=460800, metavar="BAUD",
                    help="serial speed for the backup read (default 460800; defib's own "
                         "921600 drops packets on some adapters; 0 = defib's default)")
    ap.add_argument("--flash-baud", type=int, default=0, metavar="BAUD",
                    help="serial speed for the flash write (default: defib's own, 921600)")
    ap.add_argument("--out", help="where to write the patched image")
    ap.add_argument("--yes", action="store_true", help="do not pause for confirmations")
    args = ap.parse_args()

    if not os.path.isfile(args.image):
        raise Fail("image not found: %s" % args.image)
    with open(args.image, "rb") as f:
        image = f.read()
    if len(image) != FLASH_SIZE:
        raise Fail("image must be exactly %d bytes" % FLASH_SIZE)
    print("Image: %s (U-Boot env currently has ethaddr=%s)"
          % (os.path.basename(args.image), env_get(image, "ethaddr")))

    hardware = not args.no_flash
    if hardware:
        if not args.port:
            raise Fail("--port is required (e.g. --port COM6)")
        if not shutil.which("defib"):
            raise Fail("defib is not installed or not on PATH -- see INSTALL.txt")
        if not os.path.isfile(os.path.join(HERE, AGENT)):
            raise Fail("%s must be in the same folder as this script" % AGENT)

    # ---- 1. back up the stock unit
    dump = None
    backup = args.from_backup
    if backup:
        print("Using existing backup %s" % backup)
    elif hardware and not args.skip_backup:
        backup = os.path.join(HERE, "stock_backup_%s.bin"
                              % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        print("\nSTEP 1/2 - back up the unit's current flash.")
        attempts = 3
        for attempt in range(1, attempts + 1):
            if attempt == 1:
                ask(args, "Disconnect power to the converter now. defib will then ask "
                          "you to plug it back in.")
            else:
                ask(args, "The read failed (a UART error is the usual cause), and the "
                          "agent must be restarted. Disconnect power again.")
            try:
                defib(["agent", "upload", "-c", CHIP, "-p", args.port])
                defib(["agent", "read", "-p", args.port, "-o", backup],
                      baud=args.read_baud)
                break
            except Fail as e:
                print("\nAttempt %d of %d failed: %s" % (attempt, attempts, e))
                if attempt == attempts:
                    raise Fail("could not read the unit's flash. Try a lower speed "
                               "(--read-baud 230400), check the wiring/ground, or "
                               "continue without a backup using --skip-backup --mac "
                               "<the unit's MAC>.")
    elif args.skip_backup and not args.mac:
        raise Fail("--skip-backup needs --mac")
    if backup:
        if not os.path.isfile(backup) or os.path.getsize(backup) != FLASH_SIZE:
            raise Fail("backup %s is missing or not %d bytes" % (backup, FLASH_SIZE))
        with open(backup, "rb") as f:
            dump = f.read()
        if dump.count(b"\xff") > len(dump) - 4096 or dump.count(b"\0") > len(dump) - 4096:
            raise Fail("backup is blank -- the read did not work")

    # ---- 2. work out the MAC to keep
    if args.mac:
        mac = norm_mac(args.mac)
        print("MAC given on the command line: %s" % mac)
    else:
        found = find_stock_mac(dump) if dump else None
        if found:
            mac = found
            print("Original MAC found in the unit's stock firmware: %s" % mac)
        elif args.random_mac:
            mac = random_mac()
            print("Original MAC not found; generated unique MAC %s" % mac)
        elif args.yes:
            raise Fail("original MAC not found; give --mac or --random-mac")
        else:
            print("The original MAC was not found in the backup (the unit may not run "
                  "the stock firmware).")
            ans = input("Type the MAC to use (blank = generate a unique one): ").strip()
            mac = norm_mac(ans) if ans else random_mac()
            print("Using MAC %s" % mac)
    if dump and backup and not args.from_backup:
        named = os.path.join(HERE, "stock_backup_%s.bin" % mac.replace(":", ""))
        if not os.path.exists(named):
            os.replace(backup, named)
            backup = named
        print("Backup kept as %s" % backup)

    # ---- 3. patch the image
    patched = patch_ethaddr(image, mac)
    check_patched(image, patched, mac)
    out = args.out or os.path.join(HERE, "flash_image_%s.bin" % mac.replace(":", ""))
    with open(out, "wb") as f:
        f.write(patched)
    print("Patched image written to %s (only the U-Boot environment differs)" % out)

    if not hardware:
        print("--no-flash given: stopping before touching hardware.")
        return

    # ---- 4. flash it
    print("\nSTEP 2/2 - flash the patched image (this ERASES the unit's flash).")
    ask(args, "Disconnect power to the converter, then plug it back in when defib asks.")
    defib(["agent", "flash", "-c", CHIP, "-i", out, "-p", args.port],
          baud=args.flash_baud)
    print("\nDone. Give the unit about a minute to boot, then find it in your router's")
    print("DHCP list under MAC %s (hostname gk7205v200-bt656-%s)." % (mac, mac.replace(":", "")[6:]))
    print("Log in with:  ssh root@<ip>   password: patatepatate   (change it with passwd)")
    if backup:
        print("To undo, flash %s back with:" % backup)
        print("  defib agent flash -c %s -i %s -p %s" % (CHIP, backup, args.port))


if __name__ == "__main__":
    try:
        main()
    except Fail as e:
        sys.exit("\nERROR: %s" % e)
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
