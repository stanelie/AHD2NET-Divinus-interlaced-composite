#pragma once

/* Start the ExMachino TCP server (port 5054) + mDNS _epoccam._tcp advert. */
int exmachina_start(void);

/* Feed one H.264 NAL (with Annex-B start code) to the connected viewer. */
void exmachina_send_nal(unsigned char *data, unsigned int len, int nal_type);
