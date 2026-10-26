#!/usr/bin/env python3
"""Set the USB HID polling rate of a DS4/DualSense-emulating build.
 * bInterval (flash 0x3A789) = N ms  -> host polls every N ms
 * report thread sleep (flash 0x991D: 'movs r0,#33' = 1.007 ms) -> N ms worth of 32768 Hz ticks, minus 1 tick
   so a fresh report is always ready when the host polls.
usage: patch_poll.py in.uf2 out.uf2 <ms>      (ms=1 -> 1000 Hz, 2 -> 500 Hz, 4 -> 250 Hz)
"""
import struct, sys
src, dst, ms = sys.argv[1], sys.argv[2], int(sys.argv[3])
ticks = round(ms * 32.768) - 1
assert 1 <= ms <= 8 and ticks < 256
d = bytearray(open(src, 'rb').read())
def patch(addr, old, new):
    for o in range(0, len(d), 512):
        a, n = struct.unpack_from('<II', d, o + 12)
        if a <= addr and addr + len(old) <= a + n:
            p = o + 32 + addr - a
            if bytes(d[p:p + len(old)]) != old: sys.exit('unexpected bytes at %x: %s' % (addr, d[p:p+len(old)].hex()))
            d[p:p + len(new)] = new; return
    sys.exit('address %x not found' % addr)
# thread sleep immediate: 'movs r0,#imm' is bytes <imm> 20 at 0x991C
old_i = bytes([33, 0x20]); new_i = bytes([ticks, 0x20])
for o in range(0, len(d), 512):
    pass
patch(0x991C, old_i, new_i)
patch(0x3A789, bytes([1]), bytes([ms]))
open(dst, 'wb').write(d); print('bInterval', ms, 'ms; sleep ticks', ticks)
