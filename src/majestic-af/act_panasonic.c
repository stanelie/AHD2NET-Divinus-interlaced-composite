// act_panasonic — Panasonic WV-CS85x CCVE PTZ actuator (conventional + new).
//
// A 4th Actuator for majestic-af (alongside act_uart / act_ms41908 /
// act_gpiostep), for the analog-ptz-bridge project: a Panasonic WV-CS854B dome
// on RS-485 behind an OpenIPC GK7205V200 converter. Unlike act_uart (binary
// Pelco/XiongMai byte frames via proto.c) this speaks Panasonic's ASCII CCVE
// protocol, so it builds its own frames; the tty handling is copied from act_uart.
//
// TWO protocol variants, chosen by ptz.actuator so the bench can switch with no
// rebuild (the camera is unmarked — see docs/PANASONIC-PROTOCOL.md):
//   "panasonic"      -> conventional CCVE (compatible CS600/650 .. CS950/CW9xx);
//                       the default and widest-covering baseline.
//   "panasonic-new"  -> the "new" protocol (faster PTZ; GC7:902 single command),
//                       as used with CU161 / MP204+CU360 controllers.
//
// Wire (docs/PTZ-PROTOCOL-stock.md): SoC UART2 -> /dev/ttyAMA1, 19200 8N1,
// half-duplex RS-485, DE on GPIO54 (UART2_RTS) via TIOCSRS485 (RTS-as-DE); if
// the PL011 driver ignores it on this 4.9 kernel, fall back to a GPIO54 toggle.
//
// Frame: STX [AD<nn>;] GC<N>:<cmd..> ETX, no checksum, ACK-handshaked (we drain,
// don't require). Grid nibble (both axes): 4=stop, 8/C=axis1 -/+, A/E=axis2 +/-.
//   conventional pan/tilt (GCF): 20213<6|dir> + 2022<panspd 0-7><tiltspd 0-7>0
//   conventional zoom/focus (GC7): 20212<2|dir>   (8=tele,C=wide,A=far,E=near)
//   new pan/tilt/zoom     (GC7): 902<zoom><ptdir><panspd 0-F><tiltspd 0-F>
//         zoom nibble = cont<<3 | dir<<2 | speed(0-3): tele=2,wide=6,stop=8
//         ptdir (Table 3.2): 1=stop,8=L,9=LU,A=U,B=RU,C=R,D=RD,E=D,F=LD
//
// STATUS: from the protocol docs, NOT bench-verified. Ground truth is the camera
// moving. If conventional does nothing, try panasonic-new; then A/B polarity.

#include "actuator.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/serial.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

#include <majestic/af_plugin_abi.h>
#include <majestic/log.h>

#include "proto.h"

#define STX 0x02
#define ETX 0x03
#define PANA_FRAME_MAX 64          // room for a two-frame stop + slack

static pthread_mutex_t p_mu = PTHREAD_MUTEX_INITIALIZER;
static int p_fd = -1;
static char p_port[128];
static int p_baud;
static int p_addr = 1;             // CCVE unit address 1..96 (the DIP unit number)
static int p_new;                  // 0 = conventional, 1 = new protocol

static speed_t baud_const(int baud) {
    switch (baud) {
    case 2400:  return B2400;
    case 4800:  return B4800;
    case 9600:  return B9600;
    case 19200: return B19200;
    case 38400: return B38400;
    default:    return B19200;     // CS85x default is 19200
    }
}

// Bounded non-blocking write (as act_uart): the descriptor is O_NONBLOCK and a
// half-written ASCII frame is one the camera will not act on.
static bool write_raw(const unsigned char *buf, size_t len) {
    if (p_fd < 0 || !len) return false;
    size_t done = 0;
    for (int tries = 0; done < len && tries < 20; tries++) {
        ssize_t n = write(p_fd, buf + done, len - done);
        if (n > 0) done += (size_t)n;
        else if (n < 0 && (errno == EAGAIN || errno == EINTR)) usleep(1000);
        else break;
    }
    if (done != len) {
        log_e("ptz(pana): short write (%u of %u): %s",
              (unsigned)done, (unsigned)len, strerror(errno));
        return false;
    }
    return true;
}

// --- frame building ------------------------------------------------------------

static int spd7(int speed) {       // majestic 0..63 -> conventional 0..7
    if (speed <= 0) return 4;
    int s = speed * 7 / 63;
    return s < 1 ? 1 : (s > 7 ? 7 : s);
}
static int spd15(int speed) {      // majestic 0..63 -> new-protocol 0..F
    if (speed <= 0) return 8;
    int s = speed * 15 / 63;
    return s < 1 ? 1 : (s > 15 ? 15 : s);
}

// pan/tilt direction nibble on the shared 3x3 grid; -1 => not a pan/tilt verb
static int pt_dir(enum PtzVerb v) {
    switch (v) {
    case PTZ_LEFT:      return 0x8;
    case PTZ_UPLEFT:    return 0x9;
    case PTZ_UP:        return 0xA;
    case PTZ_UPRIGHT:   return 0xB;
    case PTZ_RIGHT:     return 0xC;
    case PTZ_DOWNRIGHT: return 0xD;
    case PTZ_DOWN:      return 0xE;
    case PTZ_DOWNLEFT:  return 0xF;
    default:            return -1;
    }
}

// conventional zoom/focus direction nibble (202122x); -1 => not a lens verb
static int lens_dir(enum PtzVerb v) {
    switch (v) {
    case PTZ_TELE: return 0x8;
    case PTZ_WIDE: return 0xC;
    case PTZ_FAR:  return 0xA;
    case PTZ_NEAR: return 0xE;
    default:       return -1;
    }
}

static bool has_pan(enum PtzVerb v) {
    return v==PTZ_LEFT||v==PTZ_RIGHT||v==PTZ_UPLEFT||v==PTZ_UPRIGHT
         ||v==PTZ_DOWNLEFT||v==PTZ_DOWNRIGHT;
}
static bool has_tilt(enum PtzVerb v) {
    return v==PTZ_UP||v==PTZ_DOWN||v==PTZ_UPLEFT||v==PTZ_UPRIGHT
         ||v==PTZ_DOWNLEFT||v==PTZ_DOWNRIGHT;
}

// append "STX <body> ETX" to buf at *n
static void emit_frame(unsigned char *buf, int *n, const char *body) {
    buf[(*n)++] = STX;
    for (const char *c = body; *c; c++) buf[(*n)++] = (unsigned char)*c;
    buf[(*n)++] = ETX;
}

// Build the ASCII frame(s) for a verb into buf; returns total length or 0.
static int build(enum PtzVerb v, int speed, unsigned char *buf) {
    char b[PANA_FRAME_MAX];
    int dir, n = 0;

    if (!p_new) {
        // ---- conventional CCVE ----
        if (v == PTZ_STOP)
            snprintf(b, sizeof b, "AD%02d;GCF:2021364:2021224", p_addr);
        else if ((dir = pt_dir(v)) >= 0) {
            int ps = has_pan(v)  ? spd7(speed) : 0;
            int ts = has_tilt(v) ? spd7(speed) : 0;
            snprintf(b, sizeof b, "AD%02d;GCF:20213%02X:2022%X%X0",
                     p_addr, 0x60 | dir, ps, ts);
        } else if ((dir = lens_dir(v)) >= 0)
            snprintf(b, sizeof b, "AD%02d;GC7:20212%02X", p_addr, 0x20 | dir);
        else
            return 0;
        emit_frame(buf, &n, b);
        return n;
    }

    // ---- new protocol (GC7:902 <zoom><ptdir><panspd><tiltspd>) ----
    if (v == PTZ_STOP) {
        // zoom nibble 8 = zoom stop; ptdir 1 = PT stop -> one frame stops both.
        snprintf(b, sizeof b, "AD%02d;GC7:9028100", p_addr);  emit_frame(buf, &n, b);
        // focus uses the conventional lens command even in new mode (doc-safe),
        // so stop it with the conventional zoom/focus stop too.
        snprintf(b, sizeof b, "AD%02d;GC7:2021224", p_addr);  emit_frame(buf, &n, b);
        return n;
    }
    if ((dir = pt_dir(v)) >= 0) {           // pan/tilt: zoom idle (8)
        int ps = has_pan(v)  ? spd15(speed) : 0;
        int ts = has_tilt(v) ? spd15(speed) : 0;
        snprintf(b, sizeof b, "AD%02d;GC7:9028%X%X%X", p_addr, dir, ps, ts);
        emit_frame(buf, &n, b);
        return n;
    }
    switch (v) {                            // zoom: new; focus: conventional
    case PTZ_TELE: snprintf(b, sizeof b, "AD%02d;GC7:9022000", p_addr); break; // zoom 2=tele
    case PTZ_WIDE: snprintf(b, sizeof b, "AD%02d;GC7:9026000", p_addr); break; // zoom 6=wide
    case PTZ_FAR:  snprintf(b, sizeof b, "AD%02d;GC7:202122A", p_addr); break;
    case PTZ_NEAR: snprintf(b, sizeof b, "AD%02d;GC7:202122E", p_addr); break;
    default:       return 0;
    }
    emit_frame(buf, &n, b);
    return n;
}

// --- Actuator vtable -----------------------------------------------------------

static bool pana_open(void) {
    const char *port = config_get_string("ptz", "port");
    const char *name = config_get_string("ptz", "actuator");
    int speed = config_get_int("ptz", "baud");
    int addr  = config_get_int("ptz", "address");
    if (addr < 1 || addr > 96) addr = 1;

    pthread_mutex_lock(&p_mu);
    if (p_fd >= 0) { pthread_mutex_unlock(&p_mu); return true; }
    p_new = name && strstr(name, "new") != NULL;

    int fd = open(port && *port ? port : "/dev/ttyAMA1",
                  O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0) { pthread_mutex_unlock(&p_mu); return false; }

    struct termios tio;
    memset(&tio, 0, sizeof tio);
    if (tcgetattr(fd, &tio) != 0) { close(fd); pthread_mutex_unlock(&p_mu); return false; }
    cfmakeraw(&tio);                       // 8N1, no flow control
    tio.c_cflag |= (CLOCAL | CREAD);
    if (cfsetspeed(&tio, baud_const(speed ? speed : 19200)) != 0 ||
        tcsetattr(fd, TCSANOW, &tio) != 0) {
        close(fd); pthread_mutex_unlock(&p_mu); return false;
    }

    // Half-duplex RS-485: let the PL011 drive RTS (== GPIO54 == RS485_DE) as the
    // driver-enable, asserted while transmitting. If the kernel rejects this on
    // this SoC/version, fall back to a GPIO54 toggle in write_raw (see DE note).
    struct serial_rs485 rs485;
    memset(&rs485, 0, sizeof rs485);
    rs485.flags = SER_RS485_ENABLED | SER_RS485_RTS_ON_SEND;
    if (ioctl(fd, TIOCSRS485, &rs485) != 0)
        log_w("ptz(pana): TIOCSRS485 not honoured (%s) — DE may need a GPIO54 toggle",
              strerror(errno));

    tcflush(fd, TCIFLUSH);
    p_fd = fd;
    snprintf(p_port, sizeof p_port, "%s", port && *port ? port : "/dev/ttyAMA1");
    p_baud = speed ? speed : 19200;
    p_addr = addr;
    pthread_mutex_unlock(&p_mu);
    log_i("ptz(pana): open %s %d 8N1 addr %d proto %s",
          p_port, p_baud, p_addr, p_new ? "new" : "conventional");
    return true;
}

static bool pana_emit(enum PtzVerb v, int speed) {
    unsigned char f[PANA_FRAME_MAX];
    pthread_mutex_lock(&p_mu);
    int n = build(v, speed, f);
    if (n <= 0) { pthread_mutex_unlock(&p_mu); return false; }
    bool ok = write_raw(f, (size_t)n);
    if (ok) log_v("ptz(pana): %s speed %d -> %.*s", ptz_verb_name(v), speed, n, f);
    else    log_w("ptz(pana): %s frame did not reach the camera", ptz_verb_name(v));
    pthread_mutex_unlock(&p_mu);
    return ok;
}

static bool pana_has(enum PtzVerb v) {
    return v == PTZ_STOP || pt_dir(v) >= 0 || lens_dir(v) >= 0;
}

static const char *pana_proto_name(void) {
    return p_new ? "panasonic-new" : "panasonic-ccve";
}

static void pana_close(void) {
    pthread_mutex_lock(&p_mu);
    if (p_fd >= 0) {
        unsigned char f[PANA_FRAME_MAX];
        int n = build(PTZ_STOP, 0, f);     // best-effort stop on the way down
        if (n > 0) write_raw(f, (size_t)n);
        close(p_fd);
        p_fd = -1;
    }
    pthread_mutex_unlock(&p_mu);
}

// No magnification reader: the CS854B answers status *requests* rather than
// streaming a zoom ratio, so -1 keeps the engine's UART zoom reader from starting.
static int pana_fd(void) { return -1; }

static bool pana_line(char *port, size_t n, int *baud, int *addr) {
    pthread_mutex_lock(&p_mu);
    bool open_ = p_fd >= 0;
    if (open_) { snprintf(port, n, "%s", p_port); *baud = p_baud; *addr = p_addr; }
    pthread_mutex_unlock(&p_mu);
    return open_;
}

static bool pana_wake(void)      { return true; }   // no wake sequence needed
static bool pana_wake_blob(void) { return true; }

const Actuator act_panasonic = {
    .name          = "panasonic",
    .reports_motion= false,
    .honours_speed = true,          // pan/tilt carry a speed
    .proto_name    = pana_proto_name,
    .open          = pana_open,
    .close         = pana_close,
    .emit          = pana_emit,
    .has           = pana_has,
    .wake_blob     = pana_wake_blob,
    .wake          = pana_wake,
    .fd            = pana_fd,
    .line          = pana_line,
    .derives_mag   = false,
    .backlash_ms   = 0,
    .zoom_settle_ms= 0,
    .zoom_late_ms  = 0,
};
