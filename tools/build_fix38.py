#!/usr/bin/env python3
"""Experimental LSM6DSV hardware accel LPF2 configuration, based on fix37."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from build_fix37 import ROOT, build as build37
from make_ds4 import assemble, enc_bw
from uf2_image import Image
FILTER_HOOK=0xf35c
FILTER_CAVE=0xacd00
FILTER_OLD=bytes.fromhex('1df03ffb')

def filter_source():
    # Hook replaces the CTRL8 FS write in LSM6DSV init. Preserve FS selection.
    # SSI routines return 0 or an error, using integer argument registers.
    return '''.syntax unified
.thumb
.cpu cortex-m4
push {r4,r5,r6,lr}
sub sp,#8
orr.w r2,r2,#0x40
movw ip,#0xc9df
movt ip,#2
blx ip
mov r4,r0
movs r3,#0
str r3,[sp]
movs r0,#0
movs r1,#0x18
mov r2,sp
movw ip,#0xfe25
blx ip
orrs r4,r0
cmp r0,#0
bne 1f
ldrb.w r2,[sp]
bic.w r2,r2,#0x50
orr.w r2,r2,#8
movs r0,#0
movs r1,#0x18
movw ip,#0xc9df
movt ip,#2
blx ip
orrs r4,r0
1:
mov r0,r4
add sp,#8
pop {r4,r5,r6,lr}
'''

def build(asbin,out):
    out.mkdir(parents=True,exist_ok=True)
    code=assemble(filter_source(),asbin)
    code+=enc_bw(FILTER_CAVE+len(code),0xf360)
    if FILTER_CAVE+len(code)>0xacf00:raise ValueError('Filter cave overflow')
    with tempfile.TemporaryDirectory() as temp:
        build37(asbin,Path(temp))
        manifest=json.loads((Path(temp)/'manifest.json').read_text())
        manifest.update(purpose='experimental accelerometer hardware bandwidth limit; no physical noise validation',
            filter_cave=FILTER_CAVE,filter_bytes=len(code),accel_lpf2=True,accel_bandwidth='actual accel ODR / 20',
            accel_high_pass=False)
        for entry in manifest['profiles'].values():
            image=Image.load(Path(temp)/entry['file'])
            image.patch(FILTER_HOOK,FILTER_OLD,enc_bw(FILTER_HOOK,FILTER_CAVE))
            if image.read(FILTER_CAVE,len(code))!=b'\xff'*len(code):raise ValueError('Filter cave occupied')
            image.write(FILTER_CAVE,code)
            entry['file']=entry['file'].replace('fix37','fix38')
            entry['sha256']=hashlib.sha256(image.data).hexdigest()
            image.save(out/entry['file'])
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--as',dest='asbin',default='arm-none-eabi-as')
    p.add_argument('--out',type=Path,default=ROOT/'releases/ds4-fix38')
    a=p.parse_args();build(a.asbin,a.out)
