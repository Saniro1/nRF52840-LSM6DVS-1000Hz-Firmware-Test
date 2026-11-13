"""Execute embedded LSM FIFO reader/decoder; mock only peripheral and logging calls."""
import struct
import sys
import unittest
from pathlib import Path
from unicorn import *
from unicorn.arm_const import *
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_fix37 import ROOT, FIFO_CAVE
from uf2_image import Image
from functools import lru_cache

@lru_cache(maxsize=None)
def image(version):
    return Image.load(ROOT/f'releases/ds4-fix{version}/fix{version}-ds4-inverted.uf2')


def machine(version):
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
    u.mem_map(0,0x100000);u.mem_map(0x20000000,0x40000)
    for start,length in ((0xf0dc,0x8c),(0xf54c,0xbc),(FIFO_CAVE,0x40)):
        u.mem_write(start,image(version).read(start,length))
    u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20);u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
    u.reg_write(UC_ARM_REG_SP,0x2003f000);u.reg_write(UC_ARM_REG_LR,0x1235)
    return u


class FifoTests(unittest.TestCase):
    def test_actual_fifo_decoder_tags_signs_and_units(self):
        u=machine(37)
        acc_ptr,gyro_ptr=struct.unpack('<2I',image(37).read(0xf160,8))
        u.mem_write(acc_ptr,struct.pack('<f',1/2048));u.mem_write(gyro_ptr,struct.pack('<f',.07))
        for index in (0,1,7):
            for tag in range(32):
                for values in ((0,0,0),(-32768,32767,-1),(2048,-2048,1024)):
                    data=bytearray((index+1)*7)
                    data[index*7:index*7+7]=bytes([(tag<<3)|7])+struct.pack('<3h',*values)
                    u.mem_write(0x20010000,bytes(data))
                    u.mem_write(0x20011000,b'\xa5'*24)
                    for r,v in {UC_ARM_REG_R0:index,UC_ARM_REG_R1:0x20010000,
                                UC_ARM_REG_R2:0x20011000,UC_ARM_REG_R3:0x2001100c,
                                UC_ARM_REG_LR:0x1235,UC_ARM_REG_SP:0x2003f000}.items():u.reg_write(r,v)
                    u.emu_start(0xf0dd,0x1234,count=200)
                    self.assertEqual(u.reg_read(UC_ARM_REG_R0),{1:2,2:1}.get(tag,16))
                    if tag in (1,2):
                        dest=0x20011000 if tag==2 else 0x2001100c
                        result=struct.unpack('<3f',u.mem_read(dest,12))
                        scale=1/2048 if tag==2 else .07
                        for actual,raw in zip(result,values):self.assertAlmostEqual(actual,raw*scale,delta=.0003)
                    else:self.assertEqual(bytes(u.mem_read(0x20011000,24)),b'\xa5'*24)

    def test_bus_failures_do_not_publish_partial_fifo(self):
        # Run the real driver around mocked SSI calls, including both error logs.
        for version in (36,37):
            for status_error,data_error in ((0,0),(-5,0),(0,-5),(-5,-5)):
                for count,limit in ((0,10),(4,10),(10,4),(1023,8)):
                    u=machine(version)
                    state={'reads':0,'logs':0,'bytes':None}
                    def external(uc,addr,size,user):
                        result=None
                        if addr==0xfd70:
                            state['reads']+=1
                            uc.mem_write(uc.reg_read(UC_ARM_REG_R2),struct.pack('<H',count))
                            result=status_error
                        elif addr==0xfea0:
                            state['reads']+=1
                            state['bytes']=uc.reg_read(UC_ARM_REG_R3)
                            # Emulate a partial transfer; driver must not decode it.
                            dest=uc.reg_read(UC_ARM_REG_R2)
                            if state['bytes']:uc.mem_write(dest,b'\x10\x01')
                            result=data_error
                        elif addr==0x1aa10:result=0
                        elif addr==0x2e6fc:state['logs']+=1;result=0
                        if result is not None:
                            uc.reg_write(UC_ARM_REG_R0,result&0xffffffff)
                            uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
                    u.hook_add(UC_HOOK_CODE,external)
                    u.reg_write(UC_ARM_REG_R0,0x20010000);u.reg_write(UC_ARM_REG_R1,limit*7)
                    u.emu_start(0xf54d,0x1234,count=1000)
                    self.assertEqual(u.reg_read(UC_ARM_REG_PC),0x1234)
                    expected=0 if version==37 and (status_error or data_error) else min(count,limit)
                    self.assertEqual(u.reg_read(UC_ARM_REG_R0),expected,(version,status_error,data_error,count,limit))
                    self.assertEqual(state['bytes'],min(count,limit)*7)
                    self.assertEqual(state['reads'],2)
                    if status_error or data_error:self.assertGreater(state['logs'],0)
                    self.assertEqual(u.reg_read(UC_ARM_REG_SP),0x2003f000)

if __name__=='__main__':unittest.main()
