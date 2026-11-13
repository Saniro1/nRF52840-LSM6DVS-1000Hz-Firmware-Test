#!/usr/bin/env python3
"""Use verified VQF runtime gyro bias for HID; retain fix39 acceleration."""
import argparse
import hashlib
import json
import struct
import tempfile
from pathlib import Path
from build_fix39 import ROOT, build as build39
from make_ds4 import assemble, enc_bw
from uf2_image import Image

GYRO_HOOK=0x5486
GYRO_OLD=bytes.fromhex('04f097fa')
GYRO_RETURN=0x548a
BIAS_CAVE=0xaca80
LOAD_CAVE=0xacb80
VQF_TABLE=0x30970
LOAD_PTR=VQF_TABLE+4
BIAS_ADDR=0x20003414
TAU_ADDR=0xb9d0
REST_TAU=0.1


def bias_source():
    lines=['.syntax unified','.thumb','.cpu cortex-m4','.fpu fpv4-sp-d16',
           'push {r0,r1,r2,r3,r4,r5,ip,lr}','mrs r4,APSR','vmrs r5,fpscr',
           'vpush {s12-s15}','sub sp,#16','cmp r0,#0','beq 4f',
           'movw ip,#0x0788','movt ip,#0x2000','ldr ip,[ip]',
           'movw r3,#0x0970','movt r3,#3','cmp ip,r3','bne 4f',
           'movw ip,#0x3414','movt ip,#0x2000',
           'vldr s12,rad2deg','vldr s14,max_bias_rad']
    for axis in range(3):
        lines += [f'vldr s13,[ip,#{axis*4}]','vcmpe.f32 s13,s13','vmrs APSR_nzcv,fpscr','bvs 4f',
                  'vabs.f32 s15,s13','vcmp.f32 s15,s14','vmrs APSR_nzcv,fpscr','bhi 4f',
                  'vmul.f32 s13,s13,s12',f'vldr s15,[r1,#{axis*4}]',
                  'vsub.f32 s15,s15,s13',f'vstr s15,[sp,#{axis*4}]']
    lines += ['mov r1,sp','4:','ldr r0,[sp,#32]','ldr r2,[sp,#40]','ldr r3,[sp,#44]',
              'vmsr fpscr,r5','movw ip,#0x99b9','blx ip','add sp,#16','vpop {s12-s15}',
              'vmsr fpscr,r5','msr APSR_nzcvq,r4','pop {r0,r1,r2,r3,r4,r5,ip,lr}',
              'b.w 9f','.align 2','rad2deg: .float 57.29577951308232',
              'max_bias_rad: .float 0.08726646259971647','9:']
    return '\n'.join(lines)+'\n'


def load_source():
    # Retained payload: state[0x16c], then coefficients with gyrTs/accTs/magTs.
    # Reinitialize only volatile VQF state using its saved sample periods. Stored
    # physical gyro/accel calibration is outside this payload and unchanged.
    return '''.syntax unified
.thumb
.cpu cortex-m4
.fpu fpv4-sp-d16
vldr s0,[r0,#364]
vldr s1,[r0,#368]
vldr s2,[r0,#372]
'''


def build(asbin,out):
    out.mkdir(parents=True,exist_ok=True)
    code=assemble(bias_source(),asbin)
    code+=enc_bw(BIAS_CAVE+len(code),GYRO_RETURN)
    load=assemble(load_source(),asbin)
    load+=enc_bw(LOAD_CAVE+len(load),0xb9e8)
    if BIAS_CAVE+len(code)>LOAD_CAVE or LOAD_CAVE+len(load)>0xacc00:
        raise ValueError('Bias/load cave exceeds guarded free area')
    with tempfile.TemporaryDirectory() as temp:
        build39(asbin,Path(temp))
        manifest=json.loads((Path(temp)/'manifest.json').read_text())
        manifest.update(purpose='experimental VQF gyro bias correction; retain fix39 acceleration',
            bias_cave=BIAS_CAVE,bias_bytes=len(code),load_cave=LOAD_CAVE,load_bytes=len(load),
            gyro_bias='existing VQF rad/s estimate converted to dps and subtracted from a private HID copy',
            rest_reference_tau_s=REST_TAU,volatile_vqf_relearn_on_load=True)
        for entry in manifest['profiles'].values():
            image=Image.load(Path(temp)/entry['file'])
            # Verify state ABI and units against the actual getter and update code.
            if image.read(0xbb58,20)!=bytes.fromhex('0246024902480cf0b3ba00bf40330020b8330020'):raise ValueError('Unknown VQF getter')
            if image.read(0x180c8,14)!=bytes.fromhex('2ab1c36d1360036e5360436e9360'):raise ValueError('Unknown bias state offsets')
            if image.read(VQF_TABLE,52)!=bytes.fromhex('e9b9000029ba000055ba00007dba0000c9ba000041bb000095c7020059bb00006dbb000081c7020083c7020089bb00007dbb0000'):
                raise ValueError('Unknown VQF dispatch table')
            image.patch(GYRO_HOOK,GYRO_OLD,enc_bw(GYRO_HOOK,BIAS_CAVE))
            image.patch(TAU_ADDR,struct.pack('<f',1.114532),struct.pack('<f',REST_TAU))
            image.patch(LOAD_PTR,struct.pack('<I',0xba29),struct.pack('<I',LOAD_CAVE|1))
            for addr,payload in ((BIAS_CAVE,code),(LOAD_CAVE,load)):
                if image.read(addr,len(payload))!=b'\xff'*len(payload):raise ValueError('Cave occupied')
                image.write(addr,payload)
            entry['file']=entry['file'].replace('fix39','fix40')
            entry['sha256']=hashlib.sha256(image.data).hexdigest()
            image.save(out/entry['file'])
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--as',dest='asbin',default='arm-none-eabi-as')
    p.add_argument('--out',type=Path,default=ROOT/'releases/ds4-fix40')
    a=p.parse_args();build(a.asbin,a.out)
