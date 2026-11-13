#!/usr/bin/env python3
"""User-requested 0.10 dps soft gyro deadzone after fix40 bias correction."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from build_fix40 import ROOT, build as build40
from make_ds4 import assemble, enc_bw
from uf2_image import Image
DZ_HOOK=0x99ce
DZ_CAVE=0xace40
DZ_OLD=bytes.fromhex('f1ec017a')
DZ_RETURN=0x99d2


def source():
    return '''.syntax unified
.thumb
.cpu cortex-m4
.fpu fpv4-sp-d16
vldmia r1!,{s15}
vpush {s0,s1}
vldr s0,threshold
vabs.f32 s1,s15
vcmp.f32 s1,s0
vmrs APSR_nzcv,fpscr
bls 1f
vcmp.f32 s15,#0
vmrs APSR_nzcv,fpscr
bmi 2f
vsub.f32 s15,s15,s0
b 3f
2:
vadd.f32 s15,s15,s0
b 3f
1:
movw ip,#0
vmov s15,ip
3:
vpop {s0,s1}
b 9f
.align 2
threshold: .float 0.10
9:
'''


def build(asbin,out):
    out.mkdir(parents=True,exist_ok=True)
    code=assemble(source(),asbin)
    code+=enc_bw(DZ_CAVE+len(code),DZ_RETURN)
    if DZ_CAVE+len(code)>0xacf00:raise ValueError('Deadzone cave overflow')
    with tempfile.TemporaryDirectory() as temp:
        build40(asbin,Path(temp))
        m=json.loads((Path(temp)/'manifest.json').read_text())
        m.update(purpose='fix40 plus user-requested 0.10 dps per-axis soft gyro deadzone',
                 deadzone_cave=DZ_CAVE,deadzone_bytes=len(code),
                 gyro_deadzone_stage='degree/s float at converter input, after VQF correction when active',
                 gyro_deadzone_type='soft: sign(x) * max(abs(x) - 0.10, 0)')
        for e in m['profiles'].values():
            im=Image.load(Path(temp)/e['file'])
            im.patch(DZ_HOOK,DZ_OLD,enc_bw(DZ_HOOK,DZ_CAVE))
            if im.read(DZ_CAVE,len(code))!=b'\xff'*len(code):raise ValueError('Deadzone cave occupied')
            im.write(DZ_CAVE,code)
            e['file']=e['file'].replace('fix40','fix41');e['deadzone_dps']=0.10
            e['sha256']=hashlib.sha256(im.data).hexdigest()
            im.save(out/e['file'])
        (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--as',dest='asbin',default='arm-none-eabi-as')
    p.add_argument('--out',type=Path,default=ROOT/'releases/ds4-fix41')
    a=p.parse_args();build(a.asbin,a.out)
