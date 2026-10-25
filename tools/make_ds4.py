#!/usr/bin/env python3
"""Turn the DualSense-emulating SlimeVR build (fix19 base) into a DualShock 4 (DS4 v1, PID 0x05C4).

 * USB device descriptor at flash 0x3A714: PID 0x0CE6 (DualSense) -> 0x05C4 (DualShock 4).
 * Report builder: the block 0x97AC..0x985B (which writes a DualSense report) is replaced by a cave at
   0xAC858 that writes a real DS4 USB input report (report id 1, 64 bytes):
       [0]=1 [1..4]=sticks centred (7F 80 7F 80)  [5]=0x08 (hat released)  [7]=counter<<2
       [13..18] gyro X,Y,Z   [19..24] accel X,Y,Z   [35]=[39]=0x80 (no touch)
   gyro/accel come from the selected sensor-axis mapping, soft deadzone and gain (same maths as
   make_axis_variant.py).  Needs an ARM assembler (arm-zephyr-eabi-as / arm-none-eabi-as).

usage: make_ds4.py in_fix19.uf2 out.uf2 "+1,-2,-0" [deadzone_lsb] [gain_quarters] [--as /path/to/arm-as]
"""
import os, struct, subprocess, sys, tempfile

CAVE, HOOK, RET = 0xAC858, 0x97AC, 0x985C
HOOK_OLD = bytes.fromhex('0123' '2370')              # movs r3,#1 ; strb r3,[r4,#0]  (original code at 0x97AC)
PID_ADDR = 0x3A714 + 10
DEV_PTR = 0x20003280                                  # r0 expected by the send code at 0x985C

def parse(spec):
    m = []
    for t in spec.split(','):
        t = t.strip(); assert t[0] in '+-' and t[1] in '012' and len(t) == 2, t
        m.append((t[0] == '-', int(t[1])))
    assert sorted(s for _, s in m) == [0, 1, 2], 'each sensor axis exactly once'
    return m

def asm_text(mapping, dz, gain):
    L = ['.syntax unified', '.thumb', '.cpu cortex-m4',
         '  movs r3, #1', '  strb r3, [r4, #0]',
         '  movs r3, #0x7f', '  strb r3, [r4, #1]', '  strb r3, [r4, #3]',
         '  movs r3, #0x80', '  strb r3, [r4, #2]', '  strb r3, [r4, #4]',
         '  movs r3, #8', '  strb r3, [r4, #5]',
         '  ldrb r3, [r2]', '  adds r3, r3, #1', '  uxtb r3, r3', '  strb r3, [r2]',
         '  lsls r3, r3, #2', '  strb r3, [r4, #7]',
         '  movs r3, #0x80', '  strb r3, [r4, #35]', '  strb r3, [r4, #39]',
         '  mov.w r8, #8']
    for k, (neg, src) in enumerate(mapping):
        L += ['  ldrsh.w r2, [r0, #%d]' % (2 * src), '  ldrsh.w r3, [r1, #%d]' % (2 * src)]
        if neg: L += ['  negs r2, r2', '  negs r3, r3']
        if dz:
            L += ['  cmp r2, #%d' % dz, '  ble 1f', '  subs r2, r2, #%d' % dz, '  b 2f',
                  '1:', '  adds r2, r2, #%d' % dz, '  bmi 2f', '  movs r2, #0', '2:']
        if gain != 4:
            L += ['  mov.w ip, #%d' % gain, '  mul r2, r2, ip', '  asrs r2, r2, #2', '  ssat r2, #16, r2']
        L += ['  strb r2, [r4, #%d]' % (13 + 2 * k), '  asrs r2, r2, #8', '  strb r2, [r4, #%d]' % (14 + 2 * k),
              '  strb r3, [r4, #%d]' % (19 + 2 * k), '  asrs r3, r3, #8', '  strb r3, [r4, #%d]' % (20 + 2 * k)]
    L += ['  movw r0, #0x%x' % (DEV_PTR & 0xFFFF), '  movt r0, #0x%x' % (DEV_PTR >> 16)]
    return '\n'.join(L) + '\n'

def enc_bw(src, dst):
    off = dst - (src + 4)
    s = (off >> 24) & 1; i1 = (off >> 23) & 1; i2 = (off >> 22) & 1
    j1 = (~(i1 ^ s)) & 1; j2 = (~(i2 ^ s)) & 1
    return struct.pack('<HH', 0xF000 | (s << 10) | ((off >> 12) & 0x3FF),
                       0x9000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF))

def assemble(text, asbin):
    with tempfile.TemporaryDirectory() as t:
        open(t + '/c.s', 'w').write(text)
        subprocess.check_call([asbin, '-o', t + '/c.o', t + '/c.s'])
        subprocess.check_call([asbin.replace('-as', '-objcopy'), '-O', 'binary', '-j', '.text', t + '/c.o', t + '/c.bin'])
        return open(t + '/c.bin', 'rb').read()

def build_cave(mapping, dz, gain, asbin):
    code = assemble(asm_text(mapping, dz, gain), asbin)
    return code + enc_bw(CAVE + len(code), RET)

def main(src, dst, spec, dz=0, gain=4, asbin='arm-zephyr-eabi-as'):
    d = bytearray(open(src, 'rb').read())
    blocks = [(o,) + struct.unpack_from('<II', d, o + 12) for o in range(0, len(d), 512)]
    def find(a, n):
        for o, addr, size in blocks:
            if addr <= a and a + n <= addr + size: return o + 32 + (a - addr)
        sys.exit('address 0x%x not in image' % a)
    if bytes(d[find(0x97AC, 4):find(0x97AC, 4) + 4]) != HOOK_OLD: sys.exit('input is not fix19-style (0x97AC)')
    if bytes(d[find(PID_ADDR - 2, 4):find(PID_ADDR - 2, 4) + 4]) != bytes.fromhex('4c05e60c'): sys.exit('VID/PID not DualSense')
    code = build_cave(parse(spec), int(dz), int(gain), asbin)
    for i in range(0, len(code), 4):
        c = code[i:i + 4]; q = find(CAVE + i, len(c)); d[q:q + len(c)] = c
    h = find(HOOK, 4); d[h:h + 4] = enc_bw(HOOK, CAVE)
    p = find(PID_ADDR, 2); d[p:p + 2] = bytes.fromhex('c405')
    open(dst, 'wb').write(d)
    print('DS4 build: mapping', spec, 'deadzone', dz, 'gain/4', gain, 'cave bytes', len(code))

if __name__ == '__main__':
    a = sys.argv[1:]; asbin = 'arm-zephyr-eabi-as'
    if '--as' in a: i = a.index('--as'); asbin = a[i + 1]; del a[i:i + 2]
    if len(a) < 3: sys.exit(__doc__)
    main(*a, asbin=asbin)
