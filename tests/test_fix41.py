"""Execute the requested deadzone at the float converter input, not rounded counts."""
import hashlib
import json
import math
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_fix41 import ROOT,DZ_HOOK,DZ_CAVE
from build_fix36 import PROFILES
from make_ds4 import HOOK,RET,CAVE,parse
from test_fix40 import machine,publication,firmware,BIAS_ADDR,VQF_TABLE,AP,GP,SP,INPUT
from test_fix39 import machine as batch_machine,feed,finish,output
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *

class DeadzoneTests(unittest.TestCase):
    def test_threshold_signs_and_sub_count_precision(self):
        # Values around the threshold prove this is not a 1- or 2-count deadzone.
        vectors=[(0.,0),(.05,0),(.10,0),(.1001,0),(.125,0),(.15,0),(.2,1),(.5,6),(1.,14),(100.,1598),(3000.,32767)]
        for active in (False,True):
            u=machine(41)
            if active:u.mem_write(0x20000788,struct.pack('<I',VQF_TABLE))
            for value,counts in vectors:
                for sign in (-1,1):
                    actual=publication(u,(sign*value,sign*value,sign*value))
                    expected=sign*counts
                    if value==3000. and sign==-1:expected=-32768
                    self.assertEqual(actual,(expected,)*3,(active,value,sign))

    def test_deadzone_follows_bias_and_all_profile_mappings(self):
        bias=(.25,-.5,.125)
        for name,spec in PROFILES.items():
            u=machine(41,name);u.mem_write(0x20000788,struct.pack('<I',VQF_TABLE))
            u.mem_write(BIAS_ADDR,struct.pack('<3f',*(x*math.pi/180 for x in bias)))
            # One residual inside the deadzone, and positive/negative motion outside.
            raw=tuple(b+r for b,r in zip(bias,(.05,1.,-1.)))
            self.assertEqual(publication(u,raw),(0,14,-14))
            self.assertEqual(bytes(u.mem_read(INPUT,12)),struct.pack('<3f',*raw))
            for r,v in {UC_ARM_REG_R0:GP,UC_ARM_REG_R1:AP,UC_ARM_REG_R2:0x200051b2,
                        UC_ARM_REG_R4:0x200051b3,UC_ARM_REG_SP:SP,UC_ARM_REG_LR:0x1235}.items():u.reg_write(r,v)
            def clock(uc,addr,size,user):
                if addr==0x2faf8:
                    uc.reg_write(UC_ARM_REG_R0,32);uc.reg_write(UC_ARM_REG_R1,0)
                    uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
            u.hook_add(UC_HOOK_CODE,clock);u.emu_start(HOOK|1,RET,count=1500)
            expected=tuple((-1 if neg else 1)*(0,14,-14)[ax] for neg,ax in parse(spec))
            self.assertEqual(struct.unpack('<3h',u.mem_read(0x200051b3+13,6)),expected)

    def test_acceleration_and_interrupt_state_retained(self):
        for name in PROFILES:
            u=batch_machine(41,name)
            for _ in range(6):feed(u,(.03125,-.0625,1.),gyro=(1.,2.,3.))
            finish(u);self.assertEqual(output(u),(256,-512,8192))
            self.assertEqual(output(u,GP),(14,30,46))
        for masked in (0,1):
            u=machine(41)
            u.reg_write(UC_ARM_REG_PRIMASK,masked);u.reg_write(UC_ARM_REG_BASEPRI,0x80)
            for n in range(12):u.reg_write(UC_ARM_REG_S0+n,0x3f800000+n*8192)
            before=[u.reg_read(UC_ARM_REG_S0+n) for n in range(12)]
            self.assertEqual(publication(u,(1.,-2.,3.)),(14,-30,46))
            self.assertEqual(u.reg_read(UC_ARM_REG_PRIMASK),masked)
            self.assertEqual(u.reg_read(UC_ARM_REG_BASEPRI),0x80)
            self.assertEqual(u.reg_read(UC_ARM_REG_SP),SP)
            self.assertEqual([u.reg_read(UC_ARM_REG_S0+n) for n in range(12)],before)

    def test_hashes_and_strict_patch_boundaries(self):
        m=json.loads((ROOT/'releases/ds4-fix41/manifest.json').read_text())
        allowed=set(range(DZ_HOOK,DZ_HOOK+4))|set(range(DZ_CAVE,DZ_CAVE+m['deadzone_bytes']))
        for name in PROFILES:
            a,b=firmware(40,name),firmware(41,name)
            changed={p for p in a.locations if a.read(p,1)!=b.read(p,1)}
            self.assertTrue(changed<=allowed)
            self.assertEqual(a.read(DZ_CAVE,m['deadzone_bytes']),b'\xff'*m['deadzone_bytes'])
            self.assertEqual(hashlib.sha256(b.data).hexdigest(),m['profiles'][name]['sha256'])
            self.assertEqual(m['profiles'][name]['deadzone_dps'],.10)
            for p,n in ((CAVE,550),(0xace00,50),(0xaca80,248),(0xacb80,16),(0xa080,0x100)):
                self.assertEqual(a.read(p,n),b.read(p,n))

if __name__=='__main__':unittest.main()
