#!/usr/bin/env python3
"""Experimental coherent sensor handoff; exact guarded fix19 binary patch."""
import argparse
import hashlib
import json
from pathlib import Path
from build_fix36 import BASE, BASE_SHA, ROOT, PROFILES, source as report36
from make_ds4 import CAVE, HOOK, RET, PID_ADDR, HOOK_OLD, parse, assemble, enc_bw
from uf2_image import Image

FIFO_HOOK=0xf5e8
FIFO_CAVE=0xacc80
FIFO_OLD=bytes.fromhex('4ff4c252')
WRITER_HOOK=0x99b8
WRITER_CAVE=0xacc00
# push {r4,lr}; cbz r0,0x99fe
WRITER_OLD=bytes.fromhex('10b500b3')


def source(mapping):
    original=report36(mapping)
    snapshot=['push {r5,r6}','sub sp,#16','mrs r5,primask','cpsid i']
    for axis in range(3):
        snapshot += [f'ldrh r2,[r0,#{axis*2}]',f'strh.w r2,[sp,#{axis*2}]',
                     f'ldrh r2,[r1,#{axis*2}]',f'strh.w r2,[sp,#{6+axis*2}]']
    snapshot += ['msr primask,r5','mov r0,sp','add.w r1,sp,#6']
    marker='pop {r0,r1,r2,lr}\n'
    if original.count(marker)!=1:raise ValueError('Unknown report template')
    original=original.replace(marker,marker+'\n'.join(snapshot)+'\n')
    tail='mov.w r8,#8\n'
    return original.replace(tail,'add sp,#16\npop {r5,r6}\n'+tail)


def writer_source():
    # No Zephyr calls, blocking operations, peripheral access or floating-point
    # instructions are added. The existing pure converter executes atomically.
    return '''.syntax unified
.thumb
.cpu cortex-m4
push {r4,r5,r6,lr}
mrs r5,primask
cpsid i
bl 1f
msr primask,r5
pop {r4,r5,r6,pc}
1:
push {r4,lr}
cbz r0,2f
movw ip,#0x99bd
bx ip
2:
movw ip,#0x99ff
bx ip
'''


def build(asbin,out):
    data=BASE.read_bytes()
    if hashlib.sha256(data).hexdigest()!=BASE_SHA:raise ValueError('Unknown base')
    out.mkdir(parents=True,exist_ok=True)
    writer=assemble(writer_source(),asbin)
    fifo=assemble('.syntax unified\n.thumb\n.cpu cortex-m4\nmovs r4,#0\nmovw r2,#0x1840\n',asbin)
    fifo+=enc_bw(FIFO_CAVE+len(fifo),0xf5ec)
    manifest={'base_sha256':BASE_SHA,'hardware_validated':False,
              'purpose':'coherent sensor publication and report snapshot; no noise filtering',
              'writer_cave':WRITER_CAVE,'writer_bytes':len(writer),
              'fifo_cave':FIFO_CAVE,'fifo_bytes':len(fifo),'profiles':{}}
    for name,spec in PROFILES.items():
        image=Image(data)
        image.patch(HOOK,HOOK_OLD,enc_bw(HOOK,CAVE))
        image.patch(PID_ADDR,bytes.fromhex('e60c'),bytes.fromhex('c405'))
        image.patch(WRITER_HOOK,WRITER_OLD,enc_bw(WRITER_HOOK,WRITER_CAVE))
        image.patch(FIFO_HOOK,FIFO_OLD,enc_bw(FIFO_HOOK,FIFO_CAVE))
        if image.read(0x991c,2)!=bytes.fromhex('2120'):raise ValueError('Unknown retry timing')
        if image.read(0x3a174,4)!=bytes.fromhex('06000000'):raise ValueError('Unknown collection timing')
        if image.read(0x4f0c,6)!=bytes.fromhex('06200ef009fe'):raise ValueError('Unknown transition')
        if image.read(0x3a783,7)!=bytes.fromhex('07058003400001'):raise ValueError('Unknown endpoint')
        if image.read(0x5034,2)!=bytes.fromhex('1bd0'):raise ValueError('Diagnostic disabled')
        code=assemble(source(parse(spec)),asbin)
        code+=enc_bw(CAVE+len(code),RET)
        if CAVE+len(code)>WRITER_CAVE or WRITER_CAVE+len(writer)>FIFO_CAVE or FIFO_CAVE+len(fifo)>0xacf00:
            raise ValueError('Patch caves overlap or exceed boundary')
        if image.read(0xac8b4,CAVE+len(code)-0xac8b4)!=b'\xff'*(CAVE+len(code)-0xac8b4):
            raise ValueError('Report cave extension occupied')
        if image.read(WRITER_CAVE,len(writer))!=b'\xff'*len(writer):raise ValueError('Writer cave occupied')
        if image.read(FIFO_CAVE,len(fifo))!=b'\xff'*len(fifo):raise ValueError('FIFO cave occupied')
        image.write(CAVE,code);image.write(WRITER_CAVE,writer);image.write(FIFO_CAVE,fifo)
        path=out/f'fix37-ds4-{name}.uf2';image.save(path)
        manifest['profiles'][name]={'file':path.name,'mapping':spec,'deadzone_dps':0,
            'gain':1,'cave_bytes':len(code),'sha256':hashlib.sha256(image.data).hexdigest(),
            'usb_interval_ms':1,'report_retry_ticks':33,'active_sensor_interval_ms':6,
            'gyro_counts_per_dps':16,'sensor_handoff':'PRIMASK writer and stack snapshot','fifo_error_returns_zero':True}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--as',dest='asbin',default='arm-none-eabi-as')
    p.add_argument('--out',type=Path,default=ROOT/'releases/ds4-fix37')
    a=p.parse_args();build(a.asbin,a.out)
