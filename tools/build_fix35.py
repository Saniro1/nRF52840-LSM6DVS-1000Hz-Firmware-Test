#!/usr/bin/env python3
"""Reproducible, guarded DS4 patch builds from the known fix19 SlimeVR image."""
import argparse
import hashlib
import json
from pathlib import Path
from make_ds4 import assemble, enc_bw, parse, CAVE, HOOK, RET, PID_ADDR, HOOK_OLD
from uf2_image import Image

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'testing/CURRENT_1_gyro-accel-fix19.uf2'
BASE_SHA='ca788b4a19e95cceaf0e210c18ba4675904f3bf140129ce91b06c3c4905dc45e'
# Preserve tested pitch/horizontal directions. Handheld Z corrected to a rotation.
PROFILES={'normal':'+1,-2,-0','inverted':'-1,-2,+0','handheld':'+1,+0,-2'}

def determinant(mapping):
    axes=[a for _,a in mapping]
    inv=sum(axes[i]>axes[j] for i in range(3) for j in range(i+1,3))
    return (-1)**(inv+sum(n for n,_ in mapping))

def source(mapping, dz=4):
    if determinant(mapping)!=1: raise ValueError('Mapping must be a proper rotation')
    l=['.syntax unified','.thumb','.cpu cortex-m4',
       # Clear all 64 bytes, including reserved/touch fields (old code clears 59).
       'movs r3,#0']
    l += [f'strb.w r3,[r4,#{i}]' for i in range(64)]
    l += ['movs r3,#1','strb r3,[r4,#0]', 'movs r3,#128']
    l += [f'strb r3,[r4,#{i}]' for i in range(1,5)]
    l += ['movs r3,#8','strb r3,[r4,#5]',
          'ldrb r3,[r2]','adds r3,#1','uxtb r3,r3','strb r3,[r2]',
          'lsls r3,r3,#2','strb r3,[r4,#7]',
          'movs r3,#128','strb.w r3,[r4,#35]','strb.w r3,[r4,#39]',
          'movs r3,#27','strb.w r3,[r4,#30]',
          # Existing k_uptime_ticks() at 0x2faf8 returns 64-bit 32768 Hz ticks.
          # DS4 timestamp ticks are 16/3 us: ticks * 46875 / 8192.
          'push {r0,r1,r2,lr}',
          'movw ip,#0xfaf9','movt ip,#2','blx ip',
          'movw r2,#46875','umull r0,r3,r0,r2',
          'lsrs r0,r0,#13','orr.w r0,r0,r3,lsl #19',
          'strb r0,[r4,#10]','lsrs r0,r0,#8','strb r0,[r4,#11]',
          'pop {r0,r1,r2,lr}']
    for k,(neg,axis) in enumerate(mapping):
        l += [f'ldrsh.w r2,[r0,#{axis*2}]',f'ldrsh.w r3,[r1,#{axis*2}]']
        if neg: l += ['negs r2,r2','negs r3,r3']
        l += [f'cmp r2,#{dz}','ble 1f',f'subs r2,r2,#{dz}','b 2f',
              '1:',f'adds r2,r2,#{dz}','bmi 2f','movs r2,#0','2:',
              # Source converter uses 16 LSB/dps; JSL expects 32767/2000.
              'movw ip,#32767','mul r2,r2,ip','movw ip,#32000','sdiv r2,r2,ip',
              'ssat r2,#16,r2','ssat r3,#16,r3',
              f'strb r2,[r4,#{13+k*2}]','asrs r2,r2,#8',f'strb r2,[r4,#{14+k*2}]',
              f'strb r3,[r4,#{19+k*2}]','asrs r3,r3,#8',f'strb r3,[r4,#{20+k*2}]']
    l += ['mov.w r8,#8','movw r0,#0x3280','movt r0,#0x2000']
    return '\n'.join(l)+'\n'

def build(asbin,out):
    data=BASE.read_bytes()
    if hashlib.sha256(data).hexdigest()!=BASE_SHA: raise ValueError('Unknown base image')
    out.mkdir(parents=True,exist_ok=True)
    manifest={'base_sha256':BASE_SHA,'hardware_validated':False,'profiles':{}}
    for name,spec in PROFILES.items():
        image=Image(data)
        image.patch(HOOK,HOOK_OLD,enc_bw(HOOK,CAVE))
        image.patch(PID_ADDR,bytes.fromhex('e60c'),bytes.fromhex('c405'))
        # Queue attempts twice per USB frame; retain the original in-flight guard.
        # 33 ticks plus work can miss the next 1ms host poll. 16 ticks is 488us.
        image.patch(0x991c,bytes.fromhex('2120'),bytes.fromhex('1020'))
        # .data copy table: RAM 0x20000500..0x20000e60 <- flash 0x39f00.
        # sensor_update_time_ms at RAM 0x20000774 loads from flash 0x3a174.
        if image.read(0x2a914,12)!=bytes.fromhex('00050020600e0020009f0300'):
            raise ValueError('Unknown RAM initialization mapping')
        image.patch(0x3a174,bytes.fromhex('06000000'),bytes.fromhex('01000000'))
        # Also preserve 1ms cadence on transitions back to low-noise mode.
        image.patch(0x4f0c,bytes.fromhex('06200ef009fe'),bytes.fromhex('01200ef009fe'))
        if image.read(0x3a783,7)!=bytes.fromhex('07058003400001'): raise ValueError('Unknown HID endpoint')
        if image.read(0x5034,2)!=bytes.fromhex('1bd0'): raise ValueError('Timing diagnostic is suppressed')
        code=assemble(source(parse(spec)),asbin)
        code+=enc_bw(CAVE+len(code),RET)
        # Stay within the existing flash cave used by historical axis patches.
        if CAVE+len(code)>0xacf00: raise ValueError('Code cave exceeds reserved patch area')
        # The base has a historical axis cave through 0xac8b3; extension must be erased.
        extension=CAVE+len(code)-0xac8b4
        if extension>0 and image.read(0xac8b4,extension)!=b'\xff'*extension:
            raise ValueError('Code cave extension is occupied')
        image.write(CAVE,code)
        path=out/f'fix35-ds4-{name}.uf2';image.save(path)
        manifest['profiles'][name]={'file':path.name,'mapping':spec,'deadzone_dps':0.25,
            'gain':1,'cave_bytes':len(code),'sha256':hashlib.sha256(image.data).hexdigest(),
            'usb_interval_ms':1,'report_retry_ticks':16,'active_sensor_interval_ms':1}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--as',dest='asbin',default='arm-none-eabi-as')
    p.add_argument('--out',type=Path,default=ROOT/'releases/ds4-fix35')
    a=p.parse_args();build(a.asbin,a.out)

