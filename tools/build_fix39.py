#!/usr/bin/env python3
"""Average calibrated acceleration over the existing FIFO batch; retain fix38."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from build_fix38 import ROOT, build as build38
from make_ds4 import assemble, enc_bw
from uf2_image import Image

PER_SAMPLE_HOOK=0x547a
PER_SAMPLE_OLD=bytes.fromhex('0bf00102')  # and r2,fp,#1 (accel-valid)
PER_SAMPLE_NEW=bytes.fromhex('002200bf')  # movs r2,#0; nop (gyro path retained)
MEAN_HOOK=0x54ba
MEAN_OLD=bytes.fromhex('83ed027aa2e5')  # store final mean axis; branch to 0x5006
MEAN_CAVE=0xace00
MEAN_RETURN=0x5006


def mean_source():
    # r3 addresses the existing calibrated per-batch average in g. The count
    # guard at 0x5000 and floating-point divisions at 0x5492 remain unchanged.
    # Preserve caller state across the newly introduced converter call.
    return '''.syntax unified
.thumb
.cpu cortex-m4
.fpu fpv4-sp-d16
vstr s14,[r3,#8]
push {r0,r1,r2,r3,r4,r5,ip,lr}
mrs r5,APSR
vmrs r4,fpscr
vpush {s12-s15}
movs r0,#0
movs r2,#1
movw ip,#0x99b9
blx ip
vpop {s12-s15}
vmsr fpscr,r4
msr APSR_nzcvq,r5
pop {r0,r1,r2,r3,r4,r5,ip,lr}
'''


def build(asbin,out):
    out.mkdir(parents=True,exist_ok=True)
    code=assemble(mean_source(),asbin)
    code+=enc_bw(MEAN_CAVE+len(code),MEAN_RETURN)
    if MEAN_CAVE+len(code)>0xacf00:raise ValueError('Mean cave overflow')
    with tempfile.TemporaryDirectory() as temp:
        build38(asbin,Path(temp))
        manifest=json.loads((Path(temp)/'manifest.json').read_text())
        manifest.update(purpose='experimental valid FIFO batch mean for HID acceleration; no physical noise validation',
            mean_cave=MEAN_CAVE,mean_bytes=len(code),accel_publication='calibrated mean of valid acceleration samples per FIFO batch',
            accel_publication_period='existing collection interval; nominally 6 ms in low-noise mode')
        for entry in manifest['profiles'].values():
            image=Image.load(Path(temp)/entry['file'])
            # Guard both the nonzero-count branch and full average calculation.
            if image.read(0x5000,6)!=bytes.fromhex('002a40f04682'):raise ValueError('Unknown average count guard')
            if image.read(0x5492,40)!=bytes.fromhex('d7ed077ad7ed0c6af8eee77a86eea77ad7ed0d6a83ed007a86eea77ad7ed0e6a83ed017a86eea77a'):
                raise ValueError('Unknown average implementation')
            image.patch(PER_SAMPLE_HOOK,PER_SAMPLE_OLD,PER_SAMPLE_NEW)
            image.patch(MEAN_HOOK,MEAN_OLD,enc_bw(MEAN_HOOK,MEAN_CAVE)+bytes.fromhex('00bf'))
            if image.read(MEAN_CAVE,len(code))!=b'\xff'*len(code):raise ValueError('Mean cave occupied')
            image.write(MEAN_CAVE,code)
            entry['file']=entry['file'].replace('fix38','fix39')
            entry['sha256']=hashlib.sha256(image.data).hexdigest()
            image.save(out/entry['file'])
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--as',dest='asbin',default='arm-none-eabi-as')
    p.add_argument('--out',type=Path,default=ROOT/'releases/ds4-fix39')
    a=p.parse_args();build(a.asbin,a.out)
