#!/usr/bin/env python3
"""Tiny Thumb-2 interpreter (subset) to unit-test the report caves in a built UF2 without hardware.
It disassembles the cave bytes with objdump and executes them, then checks the report against a model
of the intended mapping and against JoyShockLibrary's DS4 USB parsing offsets.

usage: sim_cave.py build.uf2 "<mapping>" <deadzone_lsb> <gain_quarters> [ds4|ds5] [--objdump path]
"""
import random, re, struct, subprocess, sys, tempfile

CAVE = 0xAC858

def uf2_bytes(path, lo, n):
    d = open(path, 'rb').read(); out = bytearray(n)
    for o in range(0, len(d), 512):
        a, sz = struct.unpack_from('<II', d, o + 12)
        for i in range(sz):
            if lo <= a + i < lo + n: out[a + i - lo] = d[o + 32 + i]
    return bytes(out)

def disasm(code, base, objdump):
    with tempfile.NamedTemporaryFile(suffix='.bin') as f:
        f.write(code); f.flush()
        txt = subprocess.check_output([objdump, '-D', '-b', 'binary', '-m', 'arm', '-M', 'force-thumb',
                                       '--adjust-vma=0x%x' % base, f.name]).decode()
    ins = {}
    for l in txt.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\t([0-9a-f ]+)\t(\S+)\s*(.*)', l)
        if m: ins[int(m.group(1), 16)] = (m.group(3), m.group(4).split(';')[0].strip(), len(m.group(2).replace(' ', '')) // 2)
    return ins

def s32(v): v &= 0xFFFFFFFF; return v - (1 << 32) if v & 0x80000000 else v

def run(ins, regs, mem, stop):
    pc = CAVE; N = Z = 0; steps = 0
    def val(x):
        x = x.strip()
        return int(x[1:], 0) if x.startswith('#') else regs[x]
    def ea(arg):
        m = re.match(r'\[(\w+)(?:, #(-?\w+))?\]', arg); return (regs[m.group(1)] + (int(m.group(2), 0) if m.group(2) else 0)) & 0xFFFFFFFF
    def setf(v): nonlocal N, Z; N = 1 if s32(v) < 0 else 0; Z = 1 if (v & 0xFFFFFFFF) == 0 else 0
    while pc != stop:
        op, args, size = ins[pc]; steps += 1; assert steps < 5000
        nxt = pc + size; a = [x.strip() for x in re.split(r',\s*(?![^\[]*\])', args)] if args else []
        base = op.split('.')[0]
        if op in ('b', 'b.w', 'b.n'): nxt = int(a[0], 16)
        elif base in ('ble', 'bmi'):
            if (base == 'ble' and (Z or N)) or (base == 'bmi' and N): nxt = int(a[0], 16)
        elif base in ('mov', 'movs', 'movw'): regs[a[0]] = val(a[1]) & 0xFFFFFFFF; setf(regs[a[0]]) if op == 'movs' else None
        elif base == 'movt': regs[a[0]] = (regs[a[0]] & 0xFFFF) | (val(a[1]) << 16)
        elif base in ('negs',): regs[a[0]] = (-s32(regs[a[1]])) & 0xFFFFFFFF; setf(regs[a[0]])
        elif base in ('adds', 'subs'):
            x = s32(regs[a[1]]) if len(a) == 3 else s32(regs[a[0]]); y = val(a[-1])
            regs[a[0]] = (x + y if base == 'adds' else x - y) & 0xFFFFFFFF; setf(regs[a[0]])
        elif base == 'cmp': setf(s32(regs[a[0]]) - val(a[1])); N = 1 if s32(regs[a[0]]) - val(a[1]) < 0 else 0; Z = 1 if s32(regs[a[0]]) == val(a[1]) else 0
        elif base == 'mul': regs[a[0]] = (s32(regs[a[1]]) * s32(regs[a[2]])) & 0xFFFFFFFF
        elif base == 'asrs': regs[a[0]] = (s32(regs[a[1]] if len(a) == 3 else regs[a[0]]) >> val(a[-1])) & 0xFFFFFFFF; setf(regs[a[0]])
        elif base == 'lsls': regs[a[0]] = (regs[a[1]] << val(a[2])) & 0xFFFFFFFF; setf(regs[a[0]])
        elif base == 'uxtb': regs[a[0]] = regs[a[1]] & 0xFF
        elif base == 'ssat':
            n = val(a[1]); v = s32(regs[a[2]]); lo, hi = -(1 << (n - 1)), (1 << (n - 1)) - 1
            regs[a[0]] = max(lo, min(hi, v)) & 0xFFFFFFFF
        elif base == 'ldrsh': p = ea(a[1]); v = mem[p] | (mem[p + 1] << 8); regs[a[0]] = (v - 65536 if v & 0x8000 else v) & 0xFFFFFFFF
        elif base == 'ldrb': regs[a[0]] = mem[ea(a[1])]
        elif base == 'strb': mem[ea(a[1])] = regs[a[0]] & 0xFF
        else: raise SystemExit('unsupported op ' + op + ' ' + args)
        pc = nxt
    return steps

def ref_model(mapping, dz, gain, g, a):
    w16 = lambda x: ((x + 32768) & 0xFFFF) - 32768
    def one(v, neg, sg):
        v = -v if neg else v               # 32-bit in registers; only the stored halfword wraps
        if sg:
            if v > dz: v -= dz
            else: v = v + dz if v + dz < 0 else 0
            if gain != 4: v = max(-32768, min(32767, (v * gain) >> 2))
        return v
    gy = [w16(one(g[s], n, True)) for n, s in mapping]; ac = [w16(one(a[s], n, False)) for n, s in mapping]
    return gy, ac

def main():
    args = sys.argv[1:]; objdump = 'arm-zephyr-eabi-objdump'
    if '--objdump' in args: i = args.index('--objdump'); objdump = args[i + 1]; del args[i:i + 2]
    path, spec, dz, gain = args[0], args[1], int(args[2]), int(args[3]); proto = args[4] if len(args) > 4 else 'ds4'
    mapping = [(t[0] == '-', int(t[1])) for t in spec.split(',')]
    code = uf2_bytes(path, CAVE, 0x120)
    ins = disasm(code, CAVE, objdump)
    BUF, GP, AP, CP = 0x200051B3, 0x2000510C, 0x20005106, 0x200051B2
    random.seed(1); worst = 0; checks = 0
    vecs = [(0, 0, 0), (1, -1, 5), (-17, 17, 40), (100, -100, 3), (-32768, 32767, 0), (3000, -4000, 5000), (16, -16, 15)] + \
           [tuple(random.randint(-6000, 6000) for _ in range(3)) for _ in range(300)]
    for g in vecs:
        a = tuple(random.randint(-9000, 9000) for _ in range(3))
        mem = {}
        for i in range(0x40): mem[BUF + i] = 0
        mem[CP] = 0xFF if g == vecs[2] else 7
        for base, vals in ((GP, g), (AP, a)):
            for k, v in enumerate(vals): mem[base + 2 * k] = v & 0xFF; mem[base + 2 * k + 1] = (v >> 8) & 0xFF
        regs = {'r0': GP, 'r1': AP, 'r2': CP, 'r3': 0, 'r4': BUF, 'r5': 0, 'r6': 0, 'r7': 0, 'r8': 0, 'r9': 0, 'ip': 0}
        run(ins, regs, mem, 0x985C)
        pk = [mem[BUF + i] for i in range(0x40)]
        i16 = lambda o: struct.unpack_from('<h', bytes(pk), o)[0]
        gy, ac = ref_model(mapping, dz, gain, g, a)
        assert pk[0] == 1 and pk[1:5] == [0x7F, 0x80, 0x7F, 0x80] and pk[5] == 8 and pk[35] == 0x80 and pk[39] == 0x80, pk
        assert pk[7] & 3 == 0 and pk[7] == ((mem[CP] << 2) & 0xFF), (pk[7], mem[CP])
        assert (pk[31] & 4) == 0 and pk[8] == 0 and pk[9] == 0
        assert [i16(13), i16(15), i16(17)] == gy, (g, gy, [i16(13), i16(15), i16(17)])
        assert [i16(19), i16(21), i16(23)] == ac, (a, ac)
        assert regs['r0'] == 0x20003280 and regs['r8'] == 8 and regs['r4'] == BUF and regs['r5'] == 0 and regs['r6'] == 0
        checks += 1
    print('OK: %d vectors, DS4 report offsets/values match JoyShockLibrary parsing, registers preserved' % checks)

main()
