"""Execute real converter/cave code with adversarial single-core scheduling.

PRIMASK is honored by this test scheduler. Unicorn does not emulate Zephyr/NVIC.
The scheduler models an observer/writer becoming runnable at instruction edges.
"""
import struct
import sys
import unittest
from functools import lru_cache
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import *
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from uf2_image import Image
from make_ds4 import HOOK, RET, CAVE
from build_fix37 import ROOT, WRITER_CAVE, WRITER_HOOK

AP,GP,BUF,CP,SP=0x20005106,0x2000510c,0x200051b3,0x200051b2,0x2003f000


@lru_cache(maxsize=None)
def firmware(version,profile):
    return Image.load(ROOT/f'releases/ds4-fix{version}/fix{version}-ds4-{profile}.uf2')

def machine(version,profile='inverted'):
    image=firmware(version,profile)
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
    u.mem_map(0,0x100000);u.mem_map(0x20000000,0x40000)
    for start,size in ((HOOK,4),(CAVE,0x400),(WRITER_HOOK,0xbc),(WRITER_CAVE,0x100)):
        u.mem_write(start,image.read(start,size))
    u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20)
    u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
    return u


def writer_args(u,gyro=True,accel=True):
    u.mem_write(0x20010000,struct.pack('<3f',1,-2,3))
    u.mem_write(0x20010010,struct.pack('<3f',.5,-1,.25))
    registers={UC_ARM_REG_R0:int(gyro),UC_ARM_REG_R1:0x20010000,
               UC_ARM_REG_R2:int(accel),UC_ARM_REG_R3:0x20010010,
               UC_ARM_REG_SP:SP,UC_ARM_REG_LR:0x1235}
    registers.update({r:0xabc0+n for n,r in enumerate((UC_ARM_REG_R4,UC_ARM_REG_R5,
                     UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,
                     UC_ARM_REG_R10,UC_ARM_REG_R11))})
    for r,v in registers.items():u.reg_write(r,v)
    return registers


class HandoffTests(unittest.TestCase):
    def test_converter_preserves_values_flags_and_interrupt_state(self):
        for gyro in (False,True):
            for accel in (False,True):
                for masked in (0,1):
                    u=machine(37);regs=writer_args(u,gyro,accel)
                    u.reg_write(UC_ARM_REG_PRIMASK,masked)
                    u.reg_write(UC_ARM_REG_BASEPRI,0x80)
                    u.mem_write(AP,struct.pack('<6h',100,200,300,400,500,600))
                    u.emu_start(WRITER_HOOK|1,0x1234,count=1000)
                    self.assertEqual(u.reg_read(UC_ARM_REG_PC),0x1234)
                    self.assertEqual(struct.unpack('<3h',u.mem_read(AP,6)),(4096,-8192,2048) if accel else (100,200,300))
                    self.assertEqual(struct.unpack('<3h',u.mem_read(GP,6)),(16,-32,48) if gyro else (400,500,600))
                    self.assertEqual(u.reg_read(UC_ARM_REG_PRIMASK),masked)
                    self.assertEqual(u.reg_read(UC_ARM_REG_BASEPRI),0x80)
                    for r,v in regs.items():
                        if r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_LR):continue
                        self.assertEqual(u.reg_read(r),v)

    def test_observer_sees_only_completed_publication(self):
        # An eligible reader at every instruction edge exposes the old writer's
        # intermediate halfword stores. The protected writer excludes that reader.
        mixed={}
        for version in (36,37):
            u=machine(version);writer_args(u)
            old=struct.pack('<6h',100,200,300,400,500,600)
            new=struct.pack('<6h',4096,-8192,2048,16,-32,48)
            u.mem_write(AP,old);seen=[];masked_steps=[]
            def observer(uc,addr,size,user):
                if uc.reg_read(UC_ARM_REG_PRIMASK):masked_steps.append(addr)
                else:seen.append(bytes(uc.mem_read(AP,12)))
            u.hook_add(UC_HOOK_CODE,observer)
            u.emu_start(WRITER_HOOK|1,0x1234,count=1000)
            seen.append(bytes(u.mem_read(AP,12)))
            mixed[version]=sum(value not in (old,new) for value in seen)
            if version==37:
                self.assertTrue(masked_steps)
                # This is an instruction count, not a hardware latency measurement.
                self.assertLess(len(masked_steps),180)
        self.assertGreater(mixed[36],0)
        self.assertEqual(mixed[37],0)

    def test_report_snapshot_survives_writer_at_every_instruction_edge(self):
        old_a,old_g=(100,200,300),(400,500,600)
        new_a,new_g=(1000,2000,3000),(4000,5000,6000)
        def mapped(a,g):
            return (-g[1],-g[2],g[0],-a[1],-a[2],a[0])
        expected=(mapped(old_a,old_g),mapped(new_a,new_g))
        counts={36:0,37:0};runs=0
        for version in (36,37):
            # 400 exceeds the report path's instruction count. Requests arriving
            # during snapshot are deferred until PRIMASK is restored.
            for edge in range(400):
                u=machine(version)
                u.mem_write(AP,struct.pack('<6h',*old_a,*old_g))
                for r,v in {UC_ARM_REG_R0:GP,UC_ARM_REG_R1:AP,UC_ARM_REG_R2:CP,
                            UC_ARM_REG_R4:BUF,UC_ARM_REG_SP:SP,UC_ARM_REG_LR:0x1235}.items():u.reg_write(r,v)
                state={'step':0,'requested':False,'done':False}
                def scheduler(uc,addr,size,user):
                    if state['step']==edge:state['requested']=True
                    if state['requested'] and not state['done'] and not uc.reg_read(UC_ARM_REG_PRIMASK):
                        uc.mem_write(AP,struct.pack('<6h',*new_a,*new_g));state['done']=True
                    state['step']+=1
                    if addr==0x2faf8:
                        uc.reg_write(UC_ARM_REG_R0,32);uc.reg_write(UC_ARM_REG_R1,0)
                        uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
                u.hook_add(UC_HOOK_CODE,scheduler)
                u.emu_start(HOOK|1,RET,count=1000)
                result=struct.unpack('<6h',u.mem_read(BUF+13,12))
                if result not in expected:counts[version]+=1
                self.assertEqual(u.reg_read(UC_ARM_REG_SP),SP)
                self.assertEqual(u.reg_read(UC_ARM_REG_PRIMASK),0)
                runs+=1
        self.assertGreater(counts[36],0)
        self.assertEqual(counts[37],0)
        print(f'{runs} adversarial report schedules: mixed fix36={counts[36]}, fix37={counts[37]}')

if __name__=='__main__':unittest.main()
