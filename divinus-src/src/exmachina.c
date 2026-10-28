// ExMachino sender: advertises _epoccam._tcp and serves the H.264 feed over
// TCP 5054 in the EpocCam-compatible wire protocol, so this device shows up as
// a camera in the ExMachino viewer (github.com/stanelie/ExMachino).
//
// Coexists with RTSP/MJPEG (reads the same H.264 NALs). Latency-tuned:
// TCP_NODELAY, no buffering, and the "display immediately" timestamp.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>

#include "hal/support.h"
#include "network.h"

extern struct mdnsd *mdns;
extern NetInfo netinfo;

#define EXM_PORT        5054
#define EXM_MAGIC       0xDEADC0DEu
#define EXM_TYPE_VIDEO  0x00020002u
#define EXM_TYPE_CAP    0x00020005u
#define EXM_FLAG_CONFIG 8u
#define EXM_VERSION     0x12Du   /* Android profile (301) */
#define EXM_TS_NOW      0xFFFFFFFFu  /* display immediately, no viewer buffering */

static int exm_listen = -1;
static int exm_client = -1;
static pthread_mutex_t exm_mtx = PTHREAD_MUTEX_INITIALIZER;
static unsigned char exm_sps[256]; static unsigned int exm_spslen = 0;
static unsigned char exm_pps[128]; static unsigned int exm_ppslen = 0;

static void wr32(unsigned char *p, unsigned int v) {
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

static int send_all(int fd, const unsigned char *buf, unsigned int len) {
    while (len) {
        ssize_t n = send(fd, buf, len, MSG_NOSIGNAL);
        if (n <= 0) return -1;
        buf += n; len -= (unsigned int)n;
    }
    return 0;
}

/* build 28-byte header, then send header + payload to the connected viewer */
static void exm_send_msg(unsigned int type, unsigned int flags, unsigned int ts,
                         const unsigned char *payload, unsigned int plen) {
    unsigned char hdr[28];
    wr32(hdr + 0,  EXM_MAGIC);
    wr32(hdr + 4,  EXM_MAGIC);
    wr32(hdr + 8,  type);
    wr32(hdr + 12, plen + 12);   /* totalSize: the field the viewer frames on */
    wr32(hdr + 16, flags);
    wr32(hdr + 20, ts);
    wr32(hdr + 24, plen);
    pthread_mutex_lock(&exm_mtx);
    int fd = exm_client;
    if (fd >= 0) {
        if (send_all(fd, hdr, 28) || (plen && send_all(fd, payload, plen))) {
            close(fd); exm_client = -1;
            HAL_INFO("exmachina", "viewer write failed; disconnected\n");
        }
    }
    pthread_mutex_unlock(&exm_mtx);
}

static void exm_send_capability(void) {
    unsigned char pkt[28 + 324];
    memset(pkt, 0, sizeof(pkt));
    wr32(pkt + 0,  EXM_MAGIC);
    wr32(pkt + 4,  EXM_MAGIC);
    wr32(pkt + 8,  EXM_TYPE_CAP);
    wr32(pkt + 12, 324 + 12);
    wr32(pkt + 16, EXM_VERSION);
    wr32(pkt + 20, 0);
    wr32(pkt + 24, 0x01000000);
    unsigned char *pl = pkt + 28;
    float fps = 30.0f;
    wr32(pl + 0, 2);                        /* numFormats */
    wr32(pl + 4, 0x012D0500); memcpy(pl + 8,  &fps, 4);  /* 1280x720 H264 @30 */
    wr32(pl + 12, 0x011E0280); memcpy(pl + 16, &fps, 4); /* 640x480  H264 @30 (what we send) */
    pthread_mutex_lock(&exm_mtx);
    int fd = exm_client;
    if (fd >= 0 && send_all(fd, pkt, sizeof(pkt))) { close(fd); exm_client = -1; }
    pthread_mutex_unlock(&exm_mtx);
}

/* send SPS+PPS concatenated in ONE config packet (the viewer needs both in a
   single payload to build its CMVideoFormatDescription) */
static void exm_send_config(void) {
    if (!exm_spslen || !exm_ppslen) return;
    unsigned char cfg[512];
    memcpy(cfg, exm_sps, exm_spslen);
    memcpy(cfg + exm_spslen, exm_pps, exm_ppslen);
    exm_send_msg(EXM_TYPE_VIDEO, EXM_FLAG_CONFIG, 0, cfg, exm_spslen + exm_ppslen);
}

/* reads and discards the viewer's control commands (format-select, torch, ...) */
static void *exm_rx_thread(void *arg) {
    int fd = (int)(long)arg;
    unsigned char buf[512];
    while (recv(fd, buf, sizeof(buf), 0) > 0) { /* ignore */ }
    pthread_mutex_lock(&exm_mtx);
    if (exm_client == fd) { close(fd); exm_client = -1; }
    pthread_mutex_unlock(&exm_mtx);
    HAL_INFO("exmachina", "viewer disconnected\n");
    return NULL;
}

static void *exm_accept_thread(void *arg) {
    (void)arg;
    for (;;) {
        struct sockaddr_in cli; socklen_t cl = sizeof(cli);
        int fd = accept(exm_listen, (struct sockaddr *)&cli, &cl);
        if (fd < 0) { usleep(100000); continue; }
        int one = 1; setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        int sb = 65536; setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &sb, sizeof(sb));
        pthread_mutex_lock(&exm_mtx);
        if (exm_client >= 0) close(exm_client);   /* one viewer at a time */
        exm_client = fd;
        pthread_mutex_unlock(&exm_mtx);
        HAL_INFO("exmachina", "viewer connected from %s\n", inet_ntoa(cli.sin_addr));
        exm_send_capability();
        exm_send_config();
        pthread_t rx;
        if (!pthread_create(&rx, NULL, exm_rx_thread, (void *)(long)fd))
            pthread_detach(rx);
    }
    return NULL;
}

/* called per NAL from save_video_stream. `data` is the NAL incl. Annex-B start
   code; `nal_type` is the H.264 NAL type (1=slice,5=IDR,6=SEI,7=SPS,8=PPS,9=AUD) */
void exmachina_send_nal(unsigned char *data, unsigned int len, int nal_type) {
    if (exm_client < 0) {
        /* still cache SPS/PPS so a later viewer gets params immediately */
        if (nal_type == 7 && len <= sizeof(exm_sps)) { memcpy(exm_sps, data, len); exm_spslen = len; }
        else if (nal_type == 8 && len <= sizeof(exm_pps)) { memcpy(exm_pps, data, len); exm_ppslen = len; }
        return;
    }
    if (nal_type == 7) {
        if (len <= sizeof(exm_sps)) { memcpy(exm_sps, data, len); exm_spslen = len; }
    } else if (nal_type == 8) {
        if (len <= sizeof(exm_pps)) { memcpy(exm_pps, data, len); exm_ppslen = len; }
        exm_send_config();
    } else if (nal_type == 6 || nal_type == 9 || nal_type == 12) {
        return;   /* drop SEI / AUD / filler */
    } else {
        exm_send_msg(EXM_TYPE_VIDEO, 0, EXM_TS_NOW, data, len);
    }
}

int exmachina_start(void) {
    exm_listen = socket(AF_INET, SOCK_STREAM, 0);
    if (exm_listen < 0) { HAL_INFO("exmachina", "socket failed\n"); return -1; }
    int one = 1; setsockopt(exm_listen, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a; memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET; a.sin_addr.s_addr = INADDR_ANY; a.sin_port = htons(EXM_PORT);
    if (bind(exm_listen, (struct sockaddr *)&a, sizeof(a)) < 0) {
        HAL_INFO("exmachina", "bind %d failed\n", EXM_PORT);
        close(exm_listen); exm_listen = -1; return -1;
    }
    listen(exm_listen, 1);
    pthread_t t;
    if (!pthread_create(&t, NULL, exm_accept_thread, NULL)) pthread_detach(t);
    HAL_INFO("exmachina", "listening on TCP %d\n", EXM_PORT);

    if (mdns) {
        char host[80]; snprintf(host, sizeof(host), "%s.local", netinfo.host);
        char id[32] = "ahd2net", inst[48];
        FILE *f = fopen("/sys/class/net/eth0/address", "r");
        if (f) {
            char mac[32] = "";
            if (fgets(mac, sizeof(mac), f)) {
                char *d = id, *s = mac;
                while (*s) { if (*s != ':' && *s != '\n' && *s != '\r') *d++ = *s; s++; }
                *d = 0;
            }
            fclose(f);
        }
        snprintf(inst, sizeof(inst), "mobile-%.8s", id);
        char idtxt[48], iptxt[48];
        snprintf(idtxt, sizeof(idtxt), "id=%s", id);
        snprintf(iptxt, sizeof(iptxt), "ip=%s", netinfo.ipaddr[0]);
        const char *txt[] = { idtxt, iptxt, NULL };
        mdnsd_register_svc(mdns, inst, "_epoccam._tcp.local", EXM_PORT, host, txt);
        HAL_INFO("exmachina", "mDNS _epoccam._tcp registered: %s (%s)\n", inst, iptxt);
    } else {
        HAL_INFO("exmachina", "mDNS off; viewer must connect by IP:%d\n", EXM_PORT);
    }
    return 0;
}
