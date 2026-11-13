"""Execute compiled accumulation, calibration, averaging, converter and report paths.

Only fusion update is replaced by a no-op; VQF's upstream update_accel does not
modify its input. Clock is stubbed for packet tests. No physical noise is modeled.
"""
import hashlib
import json
import struct
import sys
import unittest
from functools import lru_cache
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import *
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_fix39 import ROOT,PER_SAMPLE_HOOK,MEAN_HOOK,MEAN_CAVE,MEAN_RETURN
from uf2_image import Image
from make_ds4 import HOOK,RET,CAVE,parse
from build_fix36 import PROFILES

FRAME,SP,AP,GP,AVG=0x20018000,0x2003f000,0x20005106,0x2000510c,0x2000368c

@lru_cache(maxsize=None)
def firmware(version,name):
    return Image.load(ROOT/f'releases/ds4-fix{version}/fix{version}-ds4-{name}.uf2')

def machine(version=39,name='inverted'):
    img=firmware(version,name)
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
    u.mem_map(0,0x100000);u.mem_map(0x20000000,0x40000)
    for start,length in ((0x4ffc,0x5a4),(0xa080,0x8c),(0x99b8,0xbc),(CAVE,0xacf00-CAVE),(HOOK,4)):
        u.mem_write(start,img.read(start,length))
    u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20);u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
    u.reg_write(UC_ARM_REG_SP,SP);u.reg_write(UC_ARM_REG_R7,FRAME)
    # The fusion function receives calibrated acceleration but does not mutate it.
    u.mem_write(0x20000788,struct.pack('<I',0x20014000))
    u.mem_write(0x20014010,struct.pack('<I',0x1001));u.mem_write(0x1000,b'\x70\x47')
    return u


def feed(u,accel,gyro=None):
    # Start at the actual DATA_VALID_ACCEL branch. Calibration and accumulation
    # execute from the image; so does the per-packet converter call at 0x5486.
    if accel is not None:u.mem_write(FRAME+0x3c,struct.pack('<3f',*accel))
    u.mem_write(FRAME+0xc,struct.pack('<I',int(gyro is not None)))
    if gyro is not None:u.mem_write(FRAME+0x48,struct.pack('<3f',*gyro))
    u.reg_write(UC_ARM_REG_R11,(int(accel is not None)|int(gyro is not None)*2));u.emu_start(0x5407,0x548a,count=1000)
    assert u.reg_read(UC_ARM_REG_PC)==0x548a


def finish(u):
    # Rejoin the actual count guard and average; zero-count must not divide/call.
    u.emu_start(0x4ffd,MEAN_RETURN,count=1000)
    assert u.reg_read(UC_ARM_REG_PC)==MEAN_RETURN


def output(u,addr=AP):return struct.unpack('<3h',u.mem_read(addr,6))

class BatchMeanTests(unittest.TestCase):
    def test_six_faces_retain_gravity_without_bias_or_axis_loss(self):
        for name,spec in PROFILES.items():
            for axis in range(3):
                for sign in (-1,1):
                    u=machine(name=name)
                    a=[0.,0.,0.];a[axis]=float(sign)
                    for _ in range(12):feed(u,a)
                    finish(u)
                    self.assertEqual(output(u),tuple(round(x*8192) for x in a))
                    # Run the report cave to verify final three-profile mapping.
                    def clock(uc,addr,size,user):
                        if addr==0x2faf8:
                            uc.reg_write(UC_ARM_REG_R0,32);uc.reg_write(UC_ARM_REG_R1,0)
                            uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
                    u.hook_add(UC_HOOK_CODE,clock)
                    for r,v in {UC_ARM_REG_R0:GP,UC_ARM_REG_R1:AP,UC_ARM_REG_R2:0x200051b2,
                                UC_ARM_REG_R4:0x200051b3,UC_ARM_REG_SP:SP,UC_ARM_REG_LR:0x1235}.items():u.reg_write(r,v)
                    u.emu_start(HOOK|1,RET,count=1000)
                    expected=tuple((-1 if neg else 1)*round(a[ax]*8192) for neg,ax in parse(spec))
                    self.assertEqual(struct.unpack('<3h',u.mem_read(0x200051b3+19,6)),expected)

    def test_mean_uses_all_samples_and_is_published_once(self):
        for version in (38,39):
            u=machine(version);previous=(111,222,333)
            u.mem_write(AP,struct.pack('<3h',*previous))
            samples=[(.03125,-.015625,1.),(-.03125,.015625,1.)]*6
            for a in samples:
                feed(u,a,gyro=(10.,-20.,30.))
                if version==39:self.assertEqual(output(u),previous)
            finish(u)
            self.assertEqual(output(u),(0,0,8192) if version==39 else (-256,128,8192))
            self.assertEqual(output(u,GP),(160,-320,480))

    def test_calibration_is_applied_before_average(self):
        u=machine()
        bias=(.03125,-.0625,.125)
        # Existing simple accelerometer calibration bias address from literal.
        bias_addr=struct.unpack('<I',firmware(39,'inverted').read(0xa108,4))[0]
        u.mem_write(bias_addr,struct.pack('<3f',*bias))
        for _ in range(9):feed(u,(bias[0],bias[1],1+bias[2]))
        finish(u);self.assertEqual(output(u),(0,0,8192))

    def test_empty_single_and_moving_batches(self):
        u=machine();u.mem_write(AP,struct.pack('<3h',100,200,300))
        finish(u);self.assertEqual(output(u),(100,200,300))
        feed(u,(.25,-.5,1.));finish(u);self.assertEqual(output(u),(2048,-4096,8192))
        # Start a new batch; the persistent last value is replaced on movement,
        # with no stationary freeze, threshold, or long-term historical state.
        u.mem_write(FRAME+0x1c,struct.pack('<I',0));u.mem_write(FRAME+0x30,b'\0'*12)
        for _ in range(4):feed(u,(1.,0.,0.))
        for _ in range(4):feed(u,(0.,1.,0.))
        finish(u);self.assertEqual(output(u),(4096,4096,0))

    def test_mixed_validity_counts_only_accel_and_keeps_gyro_fresh(self):
        u=machine();u.mem_write(AP,struct.pack('<3h',111,222,333))
        for i in range(5):feed(u,None,gyro=(float(i),0.,0.))
        finish(u)
        self.assertEqual(output(u),(111,222,333))
        self.assertEqual(output(u,GP),(64,0,0))
        self.assertEqual(struct.unpack('<I',u.mem_read(FRAME+0x1c,4))[0],0)
        feed(u,(.25,0.,1.))
        for _ in range(4):feed(u,None,gyro=(10.,-20.,30.))
        feed(u,(.75,0.,1.))
        finish(u)
        self.assertEqual(struct.unpack('<I',u.mem_read(FRAME+0x1c,4))[0],2)
        self.assertEqual(output(u),(4096,0,8192))
        self.assertEqual(output(u,GP),(160,-320,480))

    def test_new_call_preserves_integer_float_and_interrupt_state(self):
        for masked in (0,1):
            state={}
            for version in (38,39):
                u=machine(version)
                u.mem_write(FRAME+0x1c,struct.pack('<I',3))
                u.mem_write(FRAME+0x30,struct.pack('<3f',.75,-1.5,3.))
                registers={UC_ARM_REG_R0:0x1010,UC_ARM_REG_R1:0x1111,UC_ARM_REG_R2:0x2222,
                           UC_ARM_REG_R3:AVG,UC_ARM_REG_R4:0x4444,UC_ARM_REG_R5:0x5555,
                           UC_ARM_REG_R6:0x6666,UC_ARM_REG_R7:FRAME,UC_ARM_REG_R8:0x8888,
                           UC_ARM_REG_R9:0x9999,UC_ARM_REG_R10:0xaaaa,UC_ARM_REG_R11:0xbbbb,
                           UC_ARM_REG_R12:0xcccc,UC_ARM_REG_LR:0x1235,UC_ARM_REG_SP:SP,
                           UC_ARM_REG_PRIMASK:masked,UC_ARM_REG_BASEPRI:0x80}
                for r,v in registers.items():u.reg_write(r,v)
                u.reg_write(UC_ARM_REG_APSR,0x28000000)
                u.reg_write(UC_ARM_REG_FPSCR,0x01000000)
                for n in range(32):u.reg_write(UC_ARM_REG_S0+n,0x3f800000+n*8192)
                u.emu_start(0x5493,MEAN_RETURN,count=1000)
                regs=list(registers)+[UC_ARM_REG_APSR,UC_ARM_REG_FPSCR]+[UC_ARM_REG_S0+n for n in range(32)]
                state[version]=[u.reg_read(r) for r in regs]
                self.assertEqual(u.reg_read(UC_ARM_REG_PC),MEAN_RETURN)
                if version==39:self.assertEqual(output(u),(2048,-4096,8192))
            self.assertEqual(state[38],state[39])

    def test_patch_boundaries_and_release_hashes(self):
        manifest=json.loads((ROOT/'releases/ds4-fix39/manifest.json').read_text())
        allowed=set(range(PER_SAMPLE_HOOK,PER_SAMPLE_HOOK+4))|set(range(MEAN_HOOK,MEAN_HOOK+6))|set(range(MEAN_CAVE,MEAN_CAVE+manifest['mean_bytes']))
        for name in PROFILES:
            a,b=firmware(38,name),firmware(39,name)
            changed={p for p in a.locations if a.read(p,1)!=b.read(p,1)}
            self.assertTrue(changed<=allowed)
            self.assertEqual(a.read(MEAN_CAVE,manifest['mean_bytes']),b'\xff'*manifest['mean_bytes'])
            self.assertEqual(hashlib.sha256(b.data).hexdigest(),manifest['profiles'][name]['sha256'])
            for addr,size in ((HOOK,4),(CAVE,550),(0xa080,0x8c),(0xf54c,0xbc),(0x99b8,0xbc)):
                self.assertEqual(a.read(addr,size),b.read(addr,size))

if __name__=='__main__':unittest.main()
