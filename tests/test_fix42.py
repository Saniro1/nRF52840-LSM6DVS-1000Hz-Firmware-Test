"""Execute the complete DS4 report-loop paths and real completion callback.

USB submission, kernel clock and logging are mocked; no USB bus/Zephyr emulation.
"""
import hashlib
import json
import struct
import sys
import unittest
from functools import lru_cache
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_CODE
from unicorn.arm_const import *
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_fix42 import ROOT,ERROR_HOOK,ERROR_CAVE,RETRY_TICKS
from build_fix36 import PROFILES
from make_ds4 import parse
from uf2_image import Image
GUARD,BUF,COUNTER,SP=0x2000327c,0x200051b3,0x200051b2,0x2003f000

@lru_cache(maxsize=None)
def image(version,name):
    return Image.load(ROOT/f'releases/ds4-fix{version}/fix{version}-ds4-{name}.uf2')
@lru_cache(maxsize=None)
def flash(version,name):return image(version,name).read(0x1000,0xe9000)

class ReportLoop:
    def __init__(self,version=42,name='inverted'):
        self.u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        self.u.mem_map(0,0x100000);self.u.mem_map(0x20000000,0x40000)
        self.u.mem_write(0x1000,flash(version,name))
        self.u.reg_write(UC_ARM_REG_SP,SP);self.u.reg_write(UC_ARM_REG_LR,0x1235)
        self.start=0x9771;self.ticks=0;self.calls=[];self.result=0;self.logs=0;self.alloc=[]
        self.pending=None
        def external(uc,addr,size,user):
            value=None
            if addr==0x2faf8:
                uc.reg_write(UC_ARM_REG_R0,self.ticks);uc.reg_write(UC_ARM_REG_R1,0)
                uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR));return
            if addr==0x1e6d4:
                self.assert_guard()
                size=uc.reg_read(UC_ARM_REG_R2);assert size==64
                ptr=uc.reg_read(UC_ARM_REG_R1);assert ptr==BUF
                assert self.pending is None,'A second report was submitted in flight'
                packet=bytes(uc.mem_read(ptr,size));self.calls.append(packet)
                uc.mem_write(uc.reg_read(UC_ARM_REG_R3),struct.pack('<I',64 if self.result==0 else 0))
                if self.result==0:self.pending=packet
                value=self.result
            elif addr==0x1aa10:self.alloc.append(uc.reg_read(UC_ARM_REG_R0));value=0
            elif addr==0x2e6fc:self.logs+=1;value=0
            if value is not None:
                # Caller-saved values can change across the real backend/log APIs.
                for r in (UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R12):uc.reg_write(r,0xdeadbeef)
                uc.reg_write(UC_ARM_REG_R0,value&0xffffffff)
                uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
        self.u.hook_add(UC_HOOK_CODE,external)
    def assert_guard(self):assert self.guard()&1
    def guard(self):return struct.unpack('<I',self.u.mem_read(GUARD,4))[0]
    def iteration(self,result=0):
        self.result=result
        self.u.emu_start(self.start,0x991e,count=6000)
        assert self.u.reg_read(UC_ARM_REG_PC)==0x991e
        self.start=0x9779
        return self.u.reg_read(UC_ARM_REG_R0),self.u.reg_read(UC_ARM_REG_R1)
    def complete(self):
        assert self.pending is not None
        assert bytes(self.u.mem_read(BUF,64))==self.pending,'In-flight buffer changed'
        # Execute the actual completion callback with separate saved CPU context.
        regs=(UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,
              UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,
              UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_R12,UC_ARM_REG_LR,UC_ARM_REG_SP,
              UC_ARM_REG_APSR)
        saved={r:self.u.reg_read(r) for r in regs}
        self.u.reg_write(UC_ARM_REG_LR,0x1235)
        self.u.emu_start(0x9749,0x1234,count=1000)
        assert self.u.reg_read(UC_ARM_REG_PC)==0x1234
        self.pending=None
        for r,v in saved.items():self.u.reg_write(r,v)

class UsbReportTests(unittest.TestCase):
    def test_failed_submit_releases_guard_and_retries(self):
        for version in (41,42):
            loop=ReportLoop(version)
            loop.iteration(-11)
            self.assertEqual(len(loop.calls),1)
            self.assertGreater(loop.logs,0)
            self.assertEqual(loop.alloc,[8]) # Original error log allocation argument.
            loop.iteration(0)
            self.assertEqual(len(loop.calls),1 if version==41 else 2)
            self.assertEqual(loop.guard()&1,1)
            if version==42:
                loop.complete();self.assertEqual(loop.guard()&1,0)

    def test_inflight_buffer_is_immutable_until_real_callback(self):
        for name in PROFILES:
            loop=ReportLoop(name=name)
            self.assertEqual(loop.iteration(),(RETRY_TICKS,0))
            original=loop.pending
            for n in range(20):
                loop.ticks+=8
                loop.u.mem_write(0x2000510c,struct.pack('<3h',n,n,n))
                self.assertEqual(loop.iteration(),(RETRY_TICKS,0))
                self.assertEqual(bytes(loop.u.mem_read(BUF,64)),original)
            self.assertEqual(len(loop.calls),1)
            loop.complete();self.assertEqual(loop.guard()&1,0)
            loop.iteration();self.assertEqual(len(loop.calls),2)
            self.assertNotEqual(loop.calls[0],loop.calls[1])

    def test_repeated_ds4_frames_and_completion_cycles_all_profiles(self):
        for name,spec in PROFILES.items():
            loop=ReportLoop(name=name)
            for frame in range(1000):
                loop.ticks=(frame*32768)//1000
                loop.u.mem_write(0x2000510c,struct.pack('<3h',16,-32,48))
                loop.u.mem_write(0x20005106,struct.pack('<3h',8192,0,0))
                self.assertEqual(loop.iteration(),(RETRY_TICKS,0))
                packet=loop.pending
                self.assertEqual(len(packet),64);self.assertEqual(packet[0],1)
                self.assertEqual(packet[31]&4,0)
                self.assertEqual(packet[7]>>2,(frame+1)%64)
                self.assertEqual(struct.unpack_from('<H',packet,10)[0],(loop.ticks*46875//8192)&65535)
                expected=tuple((-1 if neg else 1)*(16,-32,48)[ax] for neg,ax in parse(spec))
                self.assertEqual(struct.unpack_from('<3h',packet,13),expected)
                loop.complete()
                self.assertEqual(loop.u.reg_read(UC_ARM_REG_SP),SP-40)
            self.assertEqual(len(loop.calls),1000)
        print('Executed 3000 full DS4 loop submissions/completions; virtual frame times, not a hardware Hz measurement')

    def test_repeated_failures_recover_without_corrupting_other_guard_bits(self):
        for status in (-5,-11,-19,-22):
            loop=ReportLoop();loop.u.mem_write(GUARD,struct.pack('<I',0x80))
            for _ in range(10):
                loop.iteration(status);self.assertEqual(loop.guard(),0x80)
            loop.iteration();self.assertEqual(loop.guard(),0x81)
            loop.complete();self.assertEqual(loop.guard(),0x80)
            self.assertEqual(len(loop.calls),11)

    def test_boundary_hash_and_1ms_endpoint_contract(self):
        m=json.loads((ROOT/'releases/ds4-fix42/manifest.json').read_text())
        allowed={0x991c}|set(range(ERROR_HOOK,ERROR_HOOK+6))|set(range(ERROR_CAVE,ERROR_CAVE+m['usb_error_bytes']))
        for name in PROFILES:
            a,b=image(41,name),image(42,name)
            changed={p for p in a.locations if a.read(p,1)!=b.read(p,1)}
            self.assertTrue(changed<=allowed)
            self.assertEqual(hashlib.sha256(b.data).hexdigest(),m['profiles'][name]['sha256'])
            self.assertEqual(b.read(0x3a783,7),bytes.fromhex('07058003400001'))
            self.assertEqual(b.read(0x3a71c,4),bytes.fromhex('4c05c405'))
            self.assertEqual(b.read(0x991c,2),bytes([8,0x20]))
            for p,n in ((0x977c,0x20),(0x9748,0x24),(0xac858,550),(0xaca80,248),
                        (0xace00,50),(0xace40,64),(0x99b8,0xbc),(0xf35c,4)):
                self.assertEqual(a.read(p,n),b.read(p,n))
        self.assertLess(RETRY_TICKS/32768,.00025)
        self.assertFalse(m['usb_rate_measured'])

if __name__=='__main__':unittest.main()
