#!/usr/bin/env python3
"""Silence the 'sensor: Expected N timesteps, got M' warning.
The check at flash 0x5034 is 'beq.n 0x506e' (skip the LOG_WRN when the counts match): bytes 1b d0.
Changing it to the unconditional 'b.n 0x506e' (1b e0) always skips the warning. Nothing else changes.
usage: patch_nowarn.py in.uf2 out.uf2
"""
import struct, sys
src, dst = sys.argv[1], sys.argv[2]
ADDR, OLD, NEW = 0x5034, bytes.fromhex('1bd0'), bytes.fromhex('1be0')
d = bytearray(open(src, 'rb').read())
for o in range(0, len(d), 512):
    a, n = struct.unpack_from('<II', d, o + 12)
    if a <= ADDR and ADDR + 2 <= a + n:
        p = o + 32 + ADDR - a
        if bytes(d[p:p + 2]) != OLD: sys.exit('unexpected bytes %s' % d[p:p + 2].hex())
        d[p:p + 2] = NEW; open(dst, 'wb').write(d); print('patched 0x5034 beq.n -> b.n'); break
else: sys.exit('address not found')
