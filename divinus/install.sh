#!/bin/sh
# Install the AHD2NET interlaced-composite video pipeline (divinus) onto an
# OpenIPC device (Goke GK7205V200 + TP9950). Run as root ON THE DEVICE:
#   tar xzf ahd2net-divinus-*.tar.gz && cd ahd2net-divinus && ./install.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)

# Stop any running instance (and its respawn supervisor) before overwriting.
if [ -x /etc/init.d/S96divinus ]; then
	/etc/init.d/S96divinus stop 2>/dev/null || true
	sleep 2
fi

cp "$HERE/divinus"        /usr/bin/divinus     && chmod 0755 /usr/bin/divinus
cp "$HERE/divinus.yaml"   /etc/divinus.yaml
cp "$HERE/bt656_ntsc.ini" /etc/bt656_ntsc.ini

# S32macname: unique hostname per unit (MAC suffix), before the network starts.
# S96divinus:  starts divinus under a respawn supervisor.
# S99bootok:   marks the boot healthy once divinus is up. Without it the stock
#              script waits for majestic, the boot counter is never cleared, and
#              the third consecutive warm reboot lands in FAILSAFE (no video).
for s in S32macname S96divinus S99bootok; do
	cp "$HERE/$s" "/etc/init.d/$s" && chmod 0755 "/etc/init.d/$s"
done

# Stop majestic autostarting so it does not hold ports 80/554. On the jffs2
# overlay this rm is a whiteout; remove the whiteout to restore majestic.
[ -e /etc/init.d/S95majestic ] && rm -f /etc/init.d/S95majestic

/etc/init.d/S32macname start
sync
/etc/init.d/S96divinus start
echo
echo "divinus installed and started on $(hostname)."
echo "  RTSP:      rtsp://<device-ip>:554/   (use TCP transport in VLC)"
echo "  Web+MJPEG: http://<device-ip>/"
echo "  ExMachino: <device-ip>:5054  (also advertised via mDNS _epoccam._tcp)"
echo "  SSH:       root / patatepatate   (change it with: passwd)"
