import hashlib
import json
from pathlib import Path
import random
import struct
import sys
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import *
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_fix35 import ROOT, BASE, BASE_SHA, PROFILES, determinant
from make_ds4 import CAVE, HOOK, RET, PID_ADDR, parse
from uf2_image import Image

class FirmwareTests(unittest.TestCase):
    def test_uf2_rejects_corruption(self):
        data=BASE.read_bytes()
        for mutate in (lambda d:d.__setitem__(0,0),
                       lambda d:struct.pack_into('<I',d,12,0),
                       lambda d:struct.pack_into('<I',d,512+20,0),
                       lambda d:struct.pack_into('<I',d,28,0)):
            d=bytearray(data);mutate(d)
            with self.assertRaises(ValueError): Image(d)
        with self.assertRaises(ValueError): Image(data[:-1])
    def test_changes_are_confined(self):
        original=Image.load(BASE)
        manifest=json.loads((ROOT/'releases/ds4-fix35/manifest.json').read_text())
        self.assertEqual(hashlib.sha256(original.data).hexdigest(),BASE_SHA)
        for name,spec in PROFILES.items():
            entry=manifest['profiles'][name]
            patched=Image.load(ROOT/'releases/ds4-fix35'/entry['file'])
            self.assertEqual(hashlib.sha256(patched.data).hexdigest(),entry['sha256'])
            allowed=set(range(HOOK,HOOK+4))|set(range(PID_ADDR,PID_ADDR+2))|{0x991c,0x4f0c,0x3a174}|set(range(CAVE,CAVE+entry['cave_bytes']))
            changed={a for a in original.locations if original.read(a,1)!=patched.read(a,1)}
            self.assertTrue(changed <= allowed)
            self.assertEqual(original.read(0x1000,0x3000),patched.read(0x1000,0x3000))
            self.assertEqual(patched.read(0x5034,2),bytes.fromhex('1bd0'))
            self.assertEqual(patched.read(0x3a783,7),bytes.fromhex('07058003400001'))
            self.assertEqual(patched.read(0x991c,2),bytes.fromhex('1020'))
            self.assertEqual(patched.read(0x3a174,4),bytes.fromhex('01000000'))
            self.assertEqual(patched.read(0x4f0c,2),bytes.fromhex('0120'))
            self.assertEqual(determinant(parse(spec)),1)
            # Everything newly occupied after the historical cave was erased flash.
            self.assertEqual(original.read(0xac8b4,CAVE+entry['cave_bytes']-0xac8b4),
                             b'\xff'*(CAVE+entry['cave_bytes']-0xac8b4))
    def test_actual_thumb_code(self):
        rng=random.Random(35)
        vectors=[(0,0,0),(4,-4,5),(-32768,32767,0),(1600,0,0),(0,1600,0),(0,0,1600)]
        vectors += [tuple(rng.randint(-32768,32767) for _ in range(3)) for _ in range(1000)]
        for name,spec in PROFILES.items():
            img=Image.load(ROOT/f'releases/ds4-fix35/fix35-ds4-{name}.uf2')
            u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
            u.mem_map(0,0x100000);u.mem_map(0x20000000,0x40000)
            u.mem_write(HOOK,img.read(HOOK,4));u.mem_write(CAVE,img.read(CAVE,0x300))
            # Trap the existing clock function only; all patched instructions execute.
            ticks=[0]
            def clock(uc,addr,size,user):
                if addr==0x2faf8:
                    uc.reg_write(UC_ARM_REG_R0,ticks[0]&0xffffffff)
                    uc.reg_write(UC_ARM_REG_R1,ticks[0]>>32)
                    uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
            u.hook_add(UC_HOOK_CODE,clock)
            gp,ap,cp,buf,sp=0x2000510c,0x20005106,0x200051b2,0x200051b3,0x2003f000
            for index,g in enumerate(vectors):
                a=tuple(rng.randint(-32768,32767) for _ in range(3))
                ticks[0]=[0,32,33,11453,11454,0xffffffff,0x100000000][index%7]+(index//7)*32
                u.mem_write(gp,struct.pack('<3h',*g));u.mem_write(ap,struct.pack('<3h',*a))
                u.mem_write(cp,bytes([index&255]));u.mem_write(buf,b'\xa5'*64)
                regs={UC_ARM_REG_R0:gp,UC_ARM_REG_R1:ap,UC_ARM_REG_R2:cp,UC_ARM_REG_R4:buf,
                      UC_ARM_REG_SP:sp,UC_ARM_REG_LR:0x1235,UC_ARM_REG_R5:0x5555,UC_ARM_REG_R6:0x6666,
                      UC_ARM_REG_R7:0x7777,UC_ARM_REG_R9:0x9999,UC_ARM_REG_R10:0xaaaa,UC_ARM_REG_R11:0xbbbb}
                for r,v in regs.items():u.reg_write(r,v)
                u.emu_start(HOOK|1,RET,count=1500)
                self.assertEqual(u.reg_read(UC_ARM_REG_PC),RET)
                packet=bytes(u.mem_read(buf,64))
                expected=bytearray(64);expected[0]=1;expected[1:5]=b'\x80'*4
                expected[5]=8;expected[7]=(((index&255)+1)<<2)&255
                struct.pack_into('<H',expected,10,((ticks[0]*46875)//8192)&65535)
                expected[30]=27;expected[35]=expected[39]=128
                for k,(neg,axis) in enumerate(parse(spec)):
                    v=-g[axis] if neg else g[axis]
                    v=max(0,abs(v)-4)*(-1 if v<0 else 1)
                    # truncation toward zero, as ARM SDIV
                    v=int(v*32767/32000)
                    av=-a[axis] if neg else a[axis]
                    struct.pack_into('<h',expected,13+k*2,max(-32768,min(32767,v)))
                    struct.pack_into('<h',expected,19+k*2,max(-32768,min(32767,av)))
                self.assertEqual(packet,bytes(expected),(name,index,g,a))
                for r in (UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,
                          UC_ARM_REG_R7,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11):
                    self.assertEqual(u.reg_read(r),regs[r])
                self.assertEqual(u.reg_read(UC_ARM_REG_R0),0x20003280)
                self.assertEqual(u.reg_read(UC_ARM_REG_R8),8)
        print('Executed 3018 ARM report vectors across normal/inverted/handheld')

if __name__=='__main__':unittest.main()
