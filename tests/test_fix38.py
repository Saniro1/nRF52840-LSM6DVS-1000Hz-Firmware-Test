"""Hardware LPF configuration/ABI tests; no synthetic noise-improvement claim."""
import hashlib
import json
import struct
import sys
import unittest
from functools import lru_cache
from pathlib import Path
from unicorn import *
from unicorn.arm_const import *
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_fix38 import ROOT,FILTER_HOOK,FILTER_CAVE
from uf2_image import Image

@lru_cache(maxsize=None)
def firmware(version,name='inverted'):
    return Image.load(ROOT/f'releases/ds4-fix{version}/fix{version}-ds4-{name}.uf2')

class FilterTests(unittest.TestCase):
    def test_configuration_preserves_scale_and_other_register_bits(self):
        for fs in range(4):
            for ctrl9 in range(256):
                self.run_configuration(fs,ctrl9)

    def test_io_errors_are_propagated(self):
        for failure in (0,1,2):
            self.run_configuration(2,0x50,failure)

    def run_configuration(self,fs,ctrl9,failure=None):
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        u.mem_map(0,0x100000);u.mem_map(0x20000000,0x40000)
        image=firmware(38)
        u.mem_write(FILTER_HOOK,image.read(FILTER_HOOK,4));u.mem_write(FILTER_CAVE,image.read(FILTER_CAVE,0x100))
        regs={UC_ARM_REG_R0:0,UC_ARM_REG_R1:0x17,UC_ARM_REG_R2:fs,
              UC_ARM_REG_SP:0x2003f000,UC_ARM_REG_LR:0x1235,
              UC_ARM_REG_R4:0x4444,UC_ARM_REG_R5:0x5555,UC_ARM_REG_R6:0x6666,
              UC_ARM_REG_R7:0x7777,UC_ARM_REG_R8:0x8888,
              UC_ARM_REG_R9:0x9999,UC_ARM_REG_R10:0xaaaa,UC_ARM_REG_R11:0xbbbb,
              UC_ARM_REG_PRIMASK:0,UC_ARM_REG_BASEPRI:0x80}
        for r,v in regs.items():u.reg_write(r,v)
        calls=[]
        def io(uc,addr,size,user):
            if addr not in (0x2c9de,0xfe24):return
            self.assertEqual(uc.reg_read(UC_ARM_REG_SP)%8,0)
            self.assertEqual(uc.reg_read(UC_ARM_REG_PRIMASK),0)
            args=[uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]
            self.assertEqual(args[0],0)
            number=len(calls);calls.append((addr,args))
            if addr==0xfe24:uc.mem_write(args[2],bytes([ctrl9]))
            uc.reg_write(UC_ARM_REG_R0,0xfffffffb if number==failure else 0)
            for r in (UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R12):uc.reg_write(r,0xdeadbeef)
            uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
        u.hook_add(UC_HOOK_CODE,io)
        u.emu_start(FILTER_HOOK|1,0xf360,count=200)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC),0xf360)
        self.assertEqual(calls[0],(0x2c9de,[0,0x17,fs|0x40]))
        self.assertEqual(calls[1][0],0xfe24);self.assertEqual(calls[1][1][1],0x18)
        if failure==1:self.assertEqual(len(calls),2)
        else:self.assertEqual(calls[2],(0x2c9de,[0,0x18,(ctrl9&~0x50)|8]))
        self.assertEqual(u.reg_read(UC_ARM_REG_R0),0 if failure is None else 0xfffffffb)
        for r,v in regs.items():
            if r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2):continue
            self.assertEqual(u.reg_read(r),v)

    def test_only_filter_hook_and_erased_cave_change_from_fix37(self):
        manifest=json.loads((ROOT/'releases/ds4-fix38/manifest.json').read_text())
        allowed=set(range(FILTER_HOOK,FILTER_HOOK+4))|set(range(FILTER_CAVE,FILTER_CAVE+manifest['filter_bytes']))
        for name in ('normal','inverted','handheld'):
            before,after=firmware(37,name),firmware(38,name)
            changed={a for a in before.locations if before.read(a,1)!=after.read(a,1)}
            self.assertTrue(changed<=allowed)
            self.assertEqual(before.read(FILTER_CAVE,manifest['filter_bytes']),b'\xff'*manifest['filter_bytes'])
            self.assertEqual(hashlib.sha256(after.data).hexdigest(),manifest['profiles'][name]['sha256'])
            # Report code, calibration, FIFO decoder and gyro code are unchanged.
            for start,size in ((0xac858,550),(0x99b8,0xbc),(0xa080,0xf0),(0xf0dc,0x8c)):
                self.assertEqual(before.read(start,size),after.read(start,size))

if __name__=='__main__':unittest.main()
