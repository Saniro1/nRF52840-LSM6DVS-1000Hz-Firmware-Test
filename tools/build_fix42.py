#!/usr/bin/env python3
"""DS4 1ms HID scheduling candidate; retain fix41 motion behavior."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from build_fix41 import ROOT, build as build41
from make_ds4 import assemble, enc_bw
from uf2_image import Image
ERROR_HOOK=0x986c
ERROR_OLD=bytes.fromhex('404611f0cff8')
ERROR_CAVE=0xacd60
ERROR_RETURN=0x9872
RETRY_TICKS=8


def error_source():
    # Submission returned failure, so no completion is owed for this attempt.
    # Release only bit 0; retain any other bits and original logging/error value.
    return '''.syntax unified
.thumb
.cpu cortex-m4
movw r3,#0x327c
movt r3,#0x2000
dmb
1:
ldrex r2,[r3]
bic.w r2,r2,#1
strex r0,r2,[r3]
cmp r0,#0
bne 1b
dmb
mov r0,r8
movw ip,#0xaa11
movt ip,#1
blx ip
'''


def build(asbin,out):
    out.mkdir(parents=True,exist_ok=True)
    code=assemble(error_source(),asbin)
    code+=enc_bw(ERROR_CAVE+len(code),ERROR_RETURN)
    if ERROR_CAVE+len(code)>0xace00:raise ValueError('USB recovery cave overlaps mean cave')
    with tempfile.TemporaryDirectory() as temp:
        build41(asbin,Path(temp))
        m=json.loads((Path(temp)/'manifest.json').read_text())
        m.update(purpose='experimental DS4 1000 USB reports/s scheduling candidate; fix41 motion retained',
                 target_usb_reports_per_second=1000,usb_rate_measured=False,
                 usb_error_cave=ERROR_CAVE,usb_error_bytes=len(code),
                 usb_submission_error_releases_guard=True)
        for e in m['profiles'].values():
            im=Image.load(Path(temp)/e['file'])
            if im.read(0x3a783,7)!=bytes.fromhex('07058003400001'):raise ValueError('Unknown full-speed HID endpoint')
            if im.read(0x985c,18)!=bytes.fromhex('2146006801ab402214f036ff044698b14046'):raise ValueError('Unknown 64-byte HID submission')
            if im.read(0x991a,10)!=bytes.fromhex('0021212020f075fc29e7'):raise ValueError('Unknown sleep path')
            if im.read(0x9928,4)!=bytes.fromhex('7c320020'):raise ValueError('Unknown in-flight guard')
            im.patch(0x991c,bytes.fromhex('2120'),bytes([RETRY_TICKS,0x20]))
            im.patch(ERROR_HOOK,ERROR_OLD,enc_bw(ERROR_HOOK,ERROR_CAVE)+bytes.fromhex('00bf'))
            if im.read(ERROR_CAVE,len(code))!=b'\xff'*len(code):raise ValueError('USB recovery cave occupied')
            im.write(ERROR_CAVE,code)
            e['file']=e['file'].replace('fix41','fix42');e['report_retry_ticks']=RETRY_TICKS
            e['sha256']=hashlib.sha256(im.data).hexdigest()
            im.save(out/e['file'])
        (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--as',dest='asbin',default='arm-none-eabi-as')
    p.add_argument('--out',type=Path,default=ROOT/'releases/ds4-fix42')
    a=p.parse_args();build(a.asbin,a.out)
