# Analog NTSC → 480 color over the AHD2NET (GK7205V200 + TP9950) — WORKING, PERSISTENT

Full-resolution (480-line) color H.264/RTSP from an NTSC composite camera through
the cheap AHD2NET converter, built on OpenIPC/divinus. Runs on the **stock
kernel** and **starts automatically at boot**.

Device: 10.8.1.31 (root). Stream: **rtsp://10.8.1.31:554/** , 640×480 H.264.

## How it works (the final architecture)

The GK7205V200 VI cannot hardware-weave an interlaced BT.656/YUV source (the
offline write path is raw-bayer only — see PROGRESS.md "VERDICT"). So the weave
is done in software, cheaply, with low latency:

1. **TP9950 → BT.656 progressive 240-line fields.** The VI captures each NTSC
   field as a 960×240 progressive frame (`scan_mode=VI_SCAN_PROGRESSIVE`). This
   is accepted by the **stock** kernel — no kernel patch needed.
2. **VI (online) → VPSS (960×240).** A small H.264 "pump" VENC channel is bound
   to the VPSS channel so the online VI→VPSS→VENC chain keeps flowing (its output
   is never served; VENC drops it when full). The weave thread taps the VPSS
   channel via `depth=3` + `HI_MPI_VI...VPSS_GetChnFrame`.
3. **Software weave + downscale.** The weave thread (`v4_image_thread`) grabs two
   consecutive fields, interleaves them line-by-line into a 960×480 frame, and
   horizontally downscales 960→640 (3:2 average for luma) → **640×480 square-pixel
   4:3**. The woven frame is written into a VB block.
   **Field order matters:** the parity (which field lands on even vs odd lines)
   was determined empirically — the second-grabbed field goes to even rows, the
   first to odd rows. The wrong order gives a 1-line zigzag = combing on *static*
   diagonals. (Verify by measuring vertical comb energy on a static scene; the
   correct order is the lower one.)
4. **VENC SendFrame → RTSP + web.** The woven 640×480 frame is pushed to BOTH the
   H.264 VENC channel and an MJPEG VENC channel with `HI_MPI_VENC_SendFrame`;
   divinus serves H.264 on RTSP + the web player, and MJPEG on `/mjpeg`.

### VENC channel budget (why no JPEG snapshot)
The GK7205V200 allows only **3 VENC channels**. They are all used: H.264 (woven,
served) + MJPEG (woven, served) + the pump (240, bound to VPSS to keep the online
chain flowing, output dropped). There is no 4th slot, so the standalone JPEG
snapshot endpoint (`/image.jpg`, which `jpeg.c` implements with its own VENC
channel) is left disabled. The live view works via H.264 and `/mjpeg`.

Gotchas when adding the MJPEG channel:
- MJPEG needs a **bigger output buffer** than H.264 — divinus sized `bufSize` as
  `w*h*3/4` (fine for compressed H.264); MJPEG rejects that with ERR_VENC_ILLEGAL_PARAM.
  Bumped to `w*h*2` for MJPG/JPG in `v4_video_create`.
- Each divinus channel also creates its own VPSS channel; the weave only taps VPSS
  chn0, so `v4_channel_bind` now **only enables VPSS chn0** in YUV mode — otherwise
  the extra (unused) VPSS channel backpressures the group and stalls everything.
- The weave thread records H.264 vs MJPEG channel indices by codec and SendFrames
  the same woven block to both; the pump takes the first free VENC slot.

Measured added latency vs single-field: ~one NTSC field period (16.6 ms) + a few
ms for the interleave/downscale copy ≈ **~22–25 ms**. (Accepted by the owner.)

The TP9950 NTSC registers (standard, 960H active, NTSC subcarrier, color killer,
burst gate) are applied automatically by the weave thread a couple seconds after
start — no external i2cset needed. The decoder's own `bt656_init` leaves it in
PAL; the thread re-pokes it to NTSC.

## Key source changes (vs stock OpenIPC/divinus, in src/hal/hisi/)
- **v4_hal.c** — the whole weave pipeline: `v4_image_thread` is the weave loop;
  `tp9950_apply_ntsc()`; a 240-field VPSS tap; VB-block dst frames fed to VENC;
  the pump channel; skip the main VPSS→VENC bind for YUV; record the 480 VENC
  channel; size the VB common pool for a 960×480 YUV block (via
  `v4_buffer_calculate_venc`, since `..._vi` is raw-bayer only and returns 0 for YUV).
- **v4_vi.h** — load `HI_MPI_VI_GetChnFrame` / `ReleaseChnFrame`.
- **v4_vpss.h** — load `HI_MPI_VPSS_GetChnFrame` / `ReleaseChnFrame`.
- **v4_venc.h** — load `HI_MPI_VENC_SendFrame`.
- **v4_sys.h** — load `HI_MPI_SYS_Mmap/Munmap` (u64 phys!) and
  `HI_MPI_VB_GetBlock/ReleaseBlock/Handle2PhysAddr`.
  The authoritative copies live in the WSL checkout ~/divinus/src/hal/hisi/.

Gen4 VIDEO_FRAME_S offsets used when hand-building frames: width@0, height@4,
field@8, pixfmt@12, stride@44, **virtual addr @96/@104/@112** (VENC null-checks
these — must point at the mapped VB block), **phys addr @120 (Y) / @128 (UV)**.

## Build
    # in the WSL checkout with the patched src:
    cd ~/divinus && rm -f src/hal/hisi/v4_hal.o && ./build.sh hisi-v4
    # -> ~/divinus/divinus  (ARM, ~406 KB)

## What is installed on the device (persistent, survives reboot)
- `/usr/bin/divinus`            — the binary (jffs2 compresses it on the overlay)
- `/etc/divinus.yaml`           — config: single H.264 channel, 640×480, RTSP on,
                                  jpeg/mjpeg off (= divinus_live.yaml here)
- `/etc/bt656_ntsc.ini`         — sensor config, progressive 240 (= bt656_prog.ini here)
- `/etc/init.d/S96divinus`      — starts divinus at boot, **under a respawn
                                  supervisor** (see "Restart / shutdown" below)
- `S95majestic` is **whiteouted** in the overlay so majestic no longer autostarts
  (frees ports 80/554). Restore it by removing the overlay whiteout.
- The kernel module is the **stock /rom** `gk7205v200_vi.ko` (the earlier binary
  patch was removed — not needed for progressive capture + software weave).

Boot sequence: stock kernel loads VI → S96divinus runs `/usr/bin/divinus` →
weave thread applies NTSC regs and starts weaving → RTSP serves 640×480.

## Not done / notes
- **No web preview**: the browser UI needs MJPEG, which is disabled (single clean
  H.264 channel). Add a second weave-fed MJPEG VENC channel to restore it.
- The 960→640 luma downscale is a 3:2 box average; chroma is 3:2 nearest. Fine for
  NTSC's real horizontal resolution; could be a proper filter if wanted.
- PTZ (custom Panasonic protocol actuator) — deferred, separate task.

## Restart / shutdown

The weave thread (`v4_image_thread`) now honours `keepRunning`: on any graceful
signal it leaves its loop, releases the ring VB blocks, tears down the pump VENC
channel (unbind VPSS chn 0 → VENC chn *pump*, then destroy), and returns — so
`media_stop`'s `pthread_join(ispPid)` completes. **Before this it was `for(;;)`
and the join blocked forever**, which is why the web UI "restart" wedged the
service (half-torn-down: port 80 and streaming gone, 554/5054 lingering) and why
SIGTERM did nothing and needed `-9`.

The web UI "restart" button is **not** an OS reboot — it sends divinus `SIGHUP`,
which means "shut down and come back". divinus's built-in `execvp()` self-restart
**cannot work on HiSi**: exec keeps the `/dev/mpp` fds open, so the re-exec'd
image finds the VB pool still initialised and dies with `ERR_VB_BUSY`
(`0xa0018012`), plus `bind 5054 failed` on the inherited socket. So:
- `main.c` no longer calls `execvp` on graceful exit; it just exits cleanly.
- `S96divinus` runs divinus under a **respawn supervisor** (`while true; do
  divinus; sleep 2; done`). A clean exit (restart button) or a crash both respawn
  a **fresh** process — new fds, clean MPP init. Verified: SIGHUP → new PID, all
  three ports back, streaming resumes, no `ERR_VB_BUSY`.

Bonus: the supervisor also auto-recovers crashes, covering the gap where the
hardware watchdog did not actually reset the wedged process.

## Device-handling gotchas
- **Stop/restart via the init script**, not `kill`: `/etc/init.d/S96divinus stop`
  (kills the supervisor first, then divinus) and `... start`. A bare `kill` of
  divinus just triggers a respawn; a bare `-9` still risks wedging the TP9950 i2c
  bus. SIGTERM now exits cleanly, but the supervisor will respawn it.
- Deploy: `S96divinus stop` → replace `/usr/bin/divinus` → `S96divinus start`.
- `/tmp` is tmpfs (cleared on reboot) — hence the persistent copies in /usr/bin and /etc.
- The overlay (jffs2) is tiny (768 KB). jffs2 compresses on write, so the 406 KB
  binary takes ~240 KB on the overlay.

## ExMachino sender (EpocCam-compatible)

The device can act as a camera source for the ExMachino viewer
(github.com/stanelie/ExMachino). New module `src/exmachina.c` + hooks in
`network.c` (startup) and `media.c` (`save_video_stream`). Coexists with
RTSP + MJPEG (reads the same woven H.264 NALs) — no toggle, always listening;
it only does work when a viewer connects.

- **Discovery:** advertises mDNS `_epoccam._tcp` on port **5054**, instance
  `mobile-<id8>` (id derived from the eth0 MAC), TXT `id` and `ip`. Requires
  `mdns: enable: true` in divinus.yaml (set it true; the web UI can turn it off).
- **Wire protocol:** 28-byte little-endian header (magic 0xDEADC0DE ×2, type,
  totalSize=payload+12, flags, timestamp, payloadLen) + payload. On connect it
  sends a capability packet (0x00020005, announces 1280x720 + 640x480 H.264) then
  SPS+PPS **concatenated in one config packet**; then each H.264 NAL as its own
  message (type 0x00020002). SPS(7)/PPS(8) MUST share one config payload — the
  viewer's decoder holds them in locals and builds its CMVideoFormatDescription
  only when both arrive together; two separate config packets never decode.
  Config is flags=8, ts=0; slices/IDR go as
  video (flags=0, ts=0xFFFFFFFF = "display immediately", lowest latency). SEI/AUD
  are dropped. One viewer at a time; viewer control commands are read + ignored.
- **Latency:** TCP_NODELAY, 64 KB send buffer, no buffering, immediate-display
  timestamp. Adds only the TCP write to the existing ~22 ms capture latency.
- **Verified:** a test client parses the capability + config + video packets and
  ffmpeg decodes a clean 640x480 H.264 frame from the stream (OSD overlay intact).
