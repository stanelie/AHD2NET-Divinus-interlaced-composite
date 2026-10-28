# Divinus BT656/interlaced port — progress

Goal: full-resolution (480i, interlaced-woven) COLOR capture of the Panasonic
WV-CS854B (NTSC composite) through the AHD2NET (GK7205V200 + TP9950), which
majestic cannot do (it rejects the interlaced VI attribute and cannot weave
fields).

## Done
- Divinus (OpenIPC/divinus, MIT) builds for this chip: `./build.sh hisi-v4`
  (toolchain auto-downloads). Confirmed GK7205V200 support, interlace model
  (progressiveOn + even-field timing), and it controls VI-VPSS mode.
- Patched `src/hal/hisi/v4_hal.c` + `v4_config.h` to add a BT656/YUV path
  (`isYuv = !rgbModeOn`): bypass ISP, skip the sensor driver (.so) and AE/AWB,
  YUV buffer sizing, guarded destroy. (See v4_hal.c here; debug prints still in.)
- Sensor config `bt656_ntsc.ini` (interlaced) / `bt656_prog.ini` (progressive)
  in Divinus's INI format; `divinus.yaml` (720x480 h264 + jpeg). NOTE: the
  `[vi_dev]` parser REQUIRES a `datarev` key (silent CONFIG_PARAM_NOT_FOUND
  without it).
- Verified on-device: config parses fully; `HI_MPI_VI_SetDevAttr` SUCCEEDS for
  progressive (ret 0). BindPipe OK.

## Blocker
- `HI_MPI_VI_CreatePipe` returns ERR_VI_INVALID_PARA (0xa0108003) for the YUV
  pipe, across ALL tested {pixFmt, prec, bypass, ispBypassOn} combos (incl.
  majestic's known-good SP420/8-bit/BypassNone) and under both the default
  VI-VPSS mode and VIOFF_VPSSON. VI-online cannot be *set* here
  (ERR_SYS_ILLEGAL_PARAM / 0xa0028009) — it appears to be the default.
- Interlaced `SetDevAttr` also returns INVALID_PARA (progressive SetDevAttr is
  fine) — a separate issue to tackle after the pipe works.

## Why stuck / next
- The toolchain's bundled SDK headers (hi_comm_vi.h) are the OLDER legacy VI API
  (DEV->CHN->WAY->CAPSEL, no pipe), so they don't define the gen4
  VI_PIPE_ATTR_S this runtime libmpi.so actually uses. Blind parameter sweeps
  can't resolve it without the real struct/validation.
- Highest-yield next steps:
  1. Obtain the real OpenIPC GK7205V200 MPP headers (VI_DEV_ATTR_S /
     VI_PIPE_ATTR_S for gen4) to confirm Divinus's struct layout + valid YUV
     pipe values.
  2. RE how majestic (working BT656 progressive) configures the VI pipe for
     YUV — it's the proven reference on this exact lib.
  3. Then enable interlaced: VIOFF weave + the interlaced SetDevAttr params.

## INTERLACED 480 — findings (2026-10-27)
- Confirmed empirically: OpenIPC's VI userspace lib (libmpi.so) REJECTS the
  interlaced BT656 dev attr. HI_MPI_VI_SetDevAttr returns ERR_VI_INVALID_PARA
  (0xa0108003) for scan=INTERLACED at BOTH 960x480 and 720x480, under VI-offline
  mode. Progressive single-field (240) is accepted; interlaced is not.
- The KERNEL drivers support interlace: both OpenIPC gk7205v200_vi.ko and the
  stock xm_vi.ko export the even-field timing HAL (VIU_HAL_SetChnVsync_Vbact/
  Vbb/Vbfb/Vbbb) and VI_HAL_SetChnScanMode. So the hardware can weave fields;
  the blocker is OpenIPC's userspace MPP validation.
- Architecture conflict for YUV on this chip:
  * raw YUV needs an ISP-bypass pipe (ISP can't init: bt656 driver never
    registers an ISP sensor -> ERR_ISP_SNS_UNREGISTER)
  * the bypass pipe only CreatePipes in VI-online (VION_VPSSON) -> single field
  * weaving two fields needs VI-offline -> which the bypass pipe rejects
- Stock firmware: statically links XiongMai's own MPP into camapp (only libc/
  libgcc are shared). XM's MPP MIGHT accept interlaced where OpenIPC's doesn't,
  OR the stock also captured a single field and upscaled to its D1 encoder
  preset (704x480). Not yet disassembled to confirm. (Note the stock was B&W
  with this camera and has no custom-protocol PTZ, so it's not a drop-in.)

### Options for REAL 480
1. Patch OpenIPC's VI path to accept interlaced (closed libmpi.so validation, or
   the kernel attr check) - deep/risky.
2. Software field-weave: capture both fields (two 240 grabs) and interleave to
   480 - complex, motion combing, and only works if the VI actually alternates
   odd/even fields (untested).
3. RE the stock camapp VI setup to confirm whether it did real 480 (via XM's
   MPP) or upscaled - a focused but non-trivial disassembly job.
4. Accept 240 as this chip's clean-path ceiling for YUV; use VPSS line-double to
   480 for display (interpolated, not real detail).

## VERDICT — kernel patched, interlaced weave is NOT possible on this SoC (2026-10-27, 2nd pass)

Pursued option 1 (patch the kernel) to the end. Result: the interlaced *attribute*
gate is removable, but a deeper, structural wall makes hardware field-weave
impossible for a BT.656/YUV source on the GK7205V200. Detail:

1. **dev-attr gate — PATCHED & VERIFIED.** The userspace libs (libhi_mpi.so,
   libgk_api.so) are pure ioctl thunks with no validation; the real check is in
   the kernel module `gk7205v200_vi.ko` (loads as module `open_vi`), function
   `VI_DRV_CheckDevAttr` @ vaddr 0x23adc. For BT656 it demanded
   `enScanMode == PROGRESSIVE` (`beq`) and returned ERR_VI_INVALID_PARA
   otherwise. One-byte patch at file offset 0x23c20 (`0x0a00004a` beq ->
   `0x9a00004a` bls) makes it accept scanmode <= 1 (interlaced OR progressive).
   After loading the patched .ko: `HI_MPI_VI_SetDevAttr` for interlaced 960x480
   now returns **0** (was 0xa0108003). The chip reports the DEV as interlaced in
   /proc/umap/vi (ScanM=I, ValidHeight 240 = one NTSC field). Patched module +
   backup: pristine original is in the read-only /rom squashfs lower layer, so
   `rm` of the overlay copy restores it.

2. **ONLINE interlaced — builds, zero usable frames.** With VI-VPSS = VION_VPSSON
   the whole pipeline comes up (CreatePipe=0, "SDK started"), but /proc shows
   `FrmErrCnt ~= IntCnt, FrmFlowCnt = 0` — every field errors, nothing flows.
   Online mode streams VI->VPSS with no DDR frame buffer, so it structurally
   cannot hold field 0 while field 1 arrives: no weave is possible online.

3. **OFFLINE interlaced — rejected deep in the driver, structural.** Weaving two
   fields into a 480 frame requires VI-offline (VI writes fields to DDR, hardware
   interleaves). With VI-VPSS = VIOFF_VPSSON, CreatePipe fails 0xa0108003.
   Traced it: VI_CreatPipe -> VI_PipeMallocMem -> (offline-only) VB prealloc ->
   `VI_DRV_GetWDRVB` @0x28720. It reads the pipe pixfmt and looks up a
   bytes-per-pixel factor from a table indexed `pixfmt-17`, valid **only for raw
   bayer formats (17..21)**. YUV420SP (26) falls off the table -> factor 0 ->
   invalid VB size -> INVALID_PARA. The entire offline write-channel path
   (GetWDRVB / SetFeWchPicConfig / SetWDRPicConfig) is built for RAW image-sensor
   capture; it cannot size or write a YUV frame. Confirmed the VB pool block was
   NOT the cause — enlarging comm[0] to a full 960x480 SP420 block changed
   nothing.

**Conclusion.** On this SoC the TP9950's BT.656/YUV can only traverse the VI in
ONLINE mode (no frame buffer -> no weave). The OFFLINE path that could weave is
hardwired for raw bayer and rejects YUV. This is not a flag that can be flipped;
it is the capture hardware/driver's data path. Therefore **true 480i hardware
weave from this converter is not achievable.** The honest ceiling for a correct,
low-latency pipeline is 240 (one full NTSC field), optionally VPSS-upscaled to
480 for display (interpolation, not real vertical detail). Software field-weave
(rejected for latency) is the only route to genuine 480 lines.

Kernel patch left in place (harmless without an interlaced config). Device left
idle (majestic and divinus both stopped).
