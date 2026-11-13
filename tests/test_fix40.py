"""Execute the compiled VQF estimator and new gyro publication path.

Synthetic constant inputs validate arithmetic/convergence, not hardware calibration.
No estimator or converter is replaced with a Python model in these tests.
"""
import hashlib
import json
import math
import struct
import sys
import unittest
from functools import lru_cache
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import *
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_fix40 import ROOT,GYRO_HOOK,GYRO_RETURN,BIAS_CAVE,LOAD_CAVE,LOAD_PTR,BIAS_ADDR,TAU_ADDR,VQF_TABLE
from uf2_image import Image
from make_ds4 import HOOK,RET,CAVE,parse
from build_fix36 import PROFILES
from test_fix39 import machine as batch_machine,feed,finish,output

GP,AP,SP,INPUT=0x2000510c,0x20005106,0x2003f000,0x20011000

def fbits(v):return struct.unpack('<I',struct.pack('<f',v))[0]

@lru_cache(maxsize=None)
def firmware(version,name='inverted'):
    return Image.load(ROOT/f'releases/ds4-fix{version}/fix{version}-ds4-{name}.uf2')

@lru_cache(maxsize=None)
def flash(version,name):return firmware(version,name).read(0x1000,0xe9000)

def machine(version=40,name='inverted'):
    image=firmware(version,name)
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
    u.mem_map(0,0x100000);u.mem_map(0x20000000,0x40000)
    u.mem_write(0x1000,flash(version,name));u.mem_write(0x20000500,image.read(0x39f00,0x960))
    u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20);u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
    u.reg_write(UC_ARM_REG_CONTROL,4)  # Active FP context, as in the sensor loop.
    return u

def call(u,pc,ptr=None):
    u.reg_write(UC_ARM_REG_SP,SP);u.reg_write(UC_ARM_REG_LR,0x1235)
    if ptr is not None:u.reg_write(UC_ARM_REG_R0,ptr)
    u.emu_start(pc|1,0x1234,count=1000000)
    assert u.reg_read(UC_ARM_REG_PC)==0x1234,hex(u.reg_read(UC_ARM_REG_PC))

def init(u,hz):
    for r in (UC_ARM_REG_S0,UC_ARM_REG_S1,UC_ARM_REG_S2):u.reg_write(r,fbits(1/hz))
    call(u,0xb9e8);u.mem_write(0x20000788,struct.pack('<I',VQF_TABLE))

def update(u,gyro,accel):
    u.mem_write(INPUT,struct.pack('<3f',*gyro));u.mem_write(INPUT+16,struct.pack('<3f',*accel))
    call(u,0xba7c,INPUT);call(u,0xbac8,INPUT+16)

def publication(u,gyro,valid=True):
    u.mem_write(INPUT,struct.pack('<3f',*gyro))
    for r,v in {UC_ARM_REG_R0:int(valid),UC_ARM_REG_R1:INPUT,UC_ARM_REG_R2:0,
                UC_ARM_REG_R3:INPUT+16,UC_ARM_REG_SP:SP,UC_ARM_REG_LR:0x1235}.items():u.reg_write(r,v)
    u.emu_start(GYRO_HOOK|1,GYRO_RETURN,count=1000)
    assert u.reg_read(UC_ARM_REG_PC)==GYRO_RETURN
    return struct.unpack('<3h',u.mem_read(GP,6))

def bias_dps(u):return tuple(v*180/math.pi for v in struct.unpack('<3f',u.mem_read(BIAS_ADDR,12)))

class GyroBiasTests(unittest.TestCase):
    def test_units_mapping_and_small_motion_without_deadzone(self):
        bias=(.25,-.5,.125)
        for name,spec in PROFILES.items():
            u=machine(name=name);u.mem_write(0x20000788,struct.pack('<I',VQF_TABLE))
            u.mem_write(BIAS_ADDR,struct.pack('<3f',*(x*math.pi/180 for x in bias)))
            raw=tuple(x+1 for x in bias)
            self.assertEqual(publication(u,raw),(16,16,16))
            self.assertEqual(bytes(u.mem_read(INPUT,12)),struct.pack('<3f',*raw))
            # 0.125 dps is preserved as two counts, not eaten by a drift deadzone.
            self.assertEqual(publication(u,tuple(x+.125 for x in bias)),(2,2,2))
            for r,v in {UC_ARM_REG_R0:GP,UC_ARM_REG_R1:AP,UC_ARM_REG_R2:0x200051b2,
                        UC_ARM_REG_R4:0x200051b3,UC_ARM_REG_SP:SP,UC_ARM_REG_LR:0x1235}.items():u.reg_write(r,v)
            def clock(uc,addr,size,user):
                if addr==0x2faf8:
                    uc.reg_write(UC_ARM_REG_R0,32);uc.reg_write(UC_ARM_REG_R1,0)
                    uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
            u.hook_add(UC_HOOK_CODE,clock);u.emu_start(HOOK|1,RET,count=1500)
            self.assertEqual(struct.unpack('<3h',u.mem_read(0x200051b3+13,6)),
                             tuple(-2 if neg else 2 for neg,_ in parse(spec)))

    def test_invalid_bias_or_other_fusion_falls_back_to_original(self):
        for bad in (float('nan'),float('inf'),-float('inf'),.1,-.1):
            for axis in range(3):
                u=machine();u.mem_write(0x20000788,struct.pack('<I',VQF_TABLE))
                b=[0.,0.,0.];b[axis]=bad
                u.mem_write(BIAS_ADDR,struct.pack('<3f',*b))
                self.assertEqual(publication(u,(1.,-2.,3.)),(16,-32,48))
        u=machine();u.mem_write(BIAS_ADDR,struct.pack('<3f',.01,.02,.03))
        # The flash initializer selects fusion_none until sensor setup completes.
        self.assertEqual(publication(u,(1.,-2.,3.)),(16,-32,48))
        u.mem_write(GP,struct.pack('<3h',100,200,300))
        self.assertEqual(publication(u,(9.,9.,9.),valid=False),(100,200,300))

    def test_abi_interrupt_and_float_state_preserved(self):
        for masked in (0,1):
            u=machine();u.mem_write(0x20000788,struct.pack('<I',VQF_TABLE))
            u.mem_write(BIAS_ADDR,struct.pack('<3f',0.,0.,0.))
            u.mem_write(INPUT,struct.pack('<3f',1.,2.,3.))
            regs={UC_ARM_REG_R0:1,UC_ARM_REG_R1:INPUT,UC_ARM_REG_R2:0,UC_ARM_REG_R3:INPUT+16,
                  UC_ARM_REG_R4:0x4444,UC_ARM_REG_R5:0x5555,UC_ARM_REG_R6:0x6666,UC_ARM_REG_R7:0x7777,
                  UC_ARM_REG_R8:0x8888,UC_ARM_REG_R9:0x9999,UC_ARM_REG_R10:0xaaaa,UC_ARM_REG_R11:0xbbbb,
                  UC_ARM_REG_R12:0xcccc,UC_ARM_REG_LR:0x1235,UC_ARM_REG_SP:SP,
                  UC_ARM_REG_PRIMASK:masked,UC_ARM_REG_BASEPRI:0x80,UC_ARM_REG_APSR:0x28000000,
                  UC_ARM_REG_FPSCR:0x01000000}
            regs.update({UC_ARM_REG_S0+n:0x3f800000+n*8192 for n in range(32)})
            # Initialize FPSCR architecturally: Unicorn's first FP access can
            # initialize its lazy FP context and discard an API-only FPSCR write.
            u.mem_write(0x1000,bytes.fromhex('e1ee105a'))  # vmsr fpscr,r5
            u.reg_write(UC_ARM_REG_R5,regs[UC_ARM_REG_FPSCR])
            u.emu_start(0x1001,0x1004,count=1)
            for r,v in regs.items():
                if r!=UC_ARM_REG_FPSCR:u.reg_write(r,v)
            u.emu_start(GYRO_HOOK|1,GYRO_RETURN,count=1500)
            self.assertEqual(u.reg_read(UC_ARM_REG_PC),GYRO_RETURN)
            for r,v in regs.items():self.assertEqual(u.reg_read(r),v,(r,masked))
            self.assertEqual(struct.unpack('<3h',u.mem_read(GP,6)),(16,32,48))

    def test_real_estimator_converges_and_preserves_deliberate_motion(self):
        raw=(.06,.31,-.44)
        results={}
        for version,hz in ((39,1920),(40,1920),(40,120)):
            u=machine(version);init(u,hz)
            # Call compiled updateGyr/updateAcc plus all their real math code.
            for _ in range(hz*20):update(u,raw,(0.,0.,1.))
            estimate=bias_dps(u)
            error=max(abs(a-b) for a,b in zip(raw,estimate));results[(version,hz)]=error
            if version==40:
                self.assertLess(error,.01)
                self.assertEqual(publication(u,raw),(0,0,0))
                moved=publication(u,tuple(x+100 for x in raw))
                self.assertTrue(all(abs(x-1600)<=1 for x in moved),moved)
            print(f'VQF binary synthetic 20s {version=} {hz=}: max bias error={error:.6f} dps')
        self.assertGreater(results[(39,1920)],.03)
        self.assertLess(results[(40,1920)],results[(39,1920)]/10)

    def test_retained_load_reinitializes_filters_and_volatile_bias_only(self):
        u=machine();init(u,1920)
        payload=bytes(u.mem_read(0x200033b8,0x16c))+bytes(u.mem_read(0x20003340,0x78))
        u.mem_write(0x20014000,payload)
        u.mem_write(BIAS_ADDR,struct.pack('<3f',.01,.02,.03))
        physical=bytes(u.mem_read(0x20003600,0x100))
        load=struct.unpack('<I',firmware(40).read(LOAD_PTR,4))[0]
        call(u,load,0x20014000)
        self.assertEqual(bytes(u.mem_read(BIAS_ADDR,12)),b'\0'*12)
        self.assertEqual(bytes(u.mem_read(0x20003600,0x100)),physical)
        self.assertAlmostEqual(struct.unpack('<f',u.mem_read(0x2000354c,4))[0],.1,places=6)
        self.assertEqual(struct.unpack('<3f',u.mem_read(0x20003340,12)),
                         struct.unpack('<3f',payload[0x16c:0x178]))

    def test_acceleration_batch_path_retained(self):
        # Reuse actual accumulation/calibration/mean execution on the new image.
        for name in PROFILES:
            u=batch_machine(40,name)
            for _ in range(6):feed(u,(.03125,-.0625,1.),gyro=(1.,2.,3.))
            finish(u)
            self.assertEqual(output(u),(256,-512,8192))

    def test_hashes_and_binary_change_boundaries(self):
        m=json.loads((ROOT/'releases/ds4-fix40/manifest.json').read_text())
        allowed=set(range(GYRO_HOOK,GYRO_HOOK+4))|set(range(TAU_ADDR,TAU_ADDR+4))|set(range(LOAD_PTR,LOAD_PTR+4))
        allowed |= set(range(BIAS_CAVE,BIAS_CAVE+m['bias_bytes']))|set(range(LOAD_CAVE,LOAD_CAVE+m['load_bytes']))
        for name in PROFILES:
            a,b=firmware(39,name),firmware(40,name)
            changed={p for p in a.locations if a.read(p,1)!=b.read(p,1)}
            self.assertTrue(changed<=allowed)
            self.assertEqual(hashlib.sha256(b.data).hexdigest(),m['profiles'][name]['sha256'])
            for p,n in ((CAVE,550),(0xace00,50),(0x99b8,0xbc),(0xa080,0x100),(0xf35c,4)):
                self.assertEqual(a.read(p,n),b.read(p,n))

if __name__=='__main__':unittest.main()
