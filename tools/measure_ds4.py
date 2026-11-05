#!/usr/bin/env python3
"""Read real USB DS4 HID reports without sleeping; measure arrival rate and stationary residuals.
Install: pip install hidapi==0.14.0.post4
List: python tools/measure_ds4.py --list
Capture: python tools/measure_ds4.py --device 0 --seconds 30 --csv capture.csv
Keep still to interpret gyro means as drift; slowly rotate to exercise each axis.
"""
import argparse
import csv
import json
import math
import statistics
import struct
import time


def decode(packet):
    if len(packet)!=64 or packet[0]!=1: raise ValueError('Expected a 64-byte DS4 USB report 1')
    if packet[31]&4: raise ValueError('DS4 reports a disconnected controller')
    return {'counter':packet[7]>>2,'timestamp':struct.unpack_from('<H',packet,10)[0],
            'gyro':[v*2000/32767 for v in struct.unpack_from('<3h',packet,13)],
            'accel':[v/8192 for v in struct.unpack_from('<3h',packet,19)]}


def summary(rows):
    if len(rows)<2: raise ValueError('At least two real reports are required')
    times=[r[0] for r in rows]
    dt=[(b-a)/1e6 for a,b in zip(times,times[1:])]
    if min(dt)<=0: raise ValueError('Arrival times must increase')
    dt.sort()
    packets=[decode(r[1]) for r in rows]
    gravity=[math.sqrt(sum(v*v for v in p['accel'])) for p in packets]
    return {'reports':len(rows),'duration_s':(times[-1]-times[0])/1e9,
            'arrival_hz':(len(rows)-1)*1e9/(times[-1]-times[0]),
            'interval_ms':{'median':statistics.median(dt),'p95':dt[int((len(dt)-1)*.95)],
                           'p99':dt[int((len(dt)-1)*.99)],'max':max(dt)},
            'gyro_mean_dps':[statistics.mean(p['gyro'][i] for p in packets) for i in range(3)],
            'gyro_stddev_dps':[statistics.pstdev(p['gyro'][i] for p in packets) for i in range(3)],
            'gravity_mean_g':statistics.mean(gravity),
            'timestamp_changes':sum(a['timestamp']!=b['timestamp'] for a,b in zip(packets,packets[1:])),
            'motion_changes':sum(a['gyro']!=b['gyro'] or a['accel']!=b['accel'] for a,b in zip(packets,packets[1:])),
            'counter_discontinuities':sum(((b['counter']-a['counter'])&63)!=1 for a,b in zip(packets,packets[1:])),
            'note':'Arrival rate is host-observed throughput. Motion changes do not measure sensor ODR. '
                   'Stationary means include the firmware deadzone; they cannot prove zero raw bias.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list',action='store_true');p.add_argument('--device',type=int)
    p.add_argument('--seconds',type=float,default=30);p.add_argument('--csv')
    p.add_argument('--analyze-csv',help='Analyze a previously captured CSV without USB')
    a=p.parse_args()
    if a.analyze_csv:
        with open(a.analyze_csv,newline='') as f:
            rows=[(int(r['arrival_ns']),bytes.fromhex(r['report_hex'])) for r in csv.DictReader(f)]
        print(json.dumps(summary(rows),indent=2));return
    import hid
    devices=[d for d in hid.enumerate(0x054c,0x05c4) if d.get('usage_page') in (None,0,1)]
    if a.list:
        for i,d in enumerate(devices):print(i,d.get('manufacturer_string'),d.get('product_string'),d.get('serial_number'))
        return
    if a.device is None or not 0<=a.device<len(devices):p.error('Use --list, then select --device INDEX explicitly')
    if not 0<a.seconds<=3600:p.error('--seconds must be in (0,3600]')
    rows=[]; invalid=0
    device=hid.device();device.open_path(devices[a.device]['path'])
    try:
        # Discard preexisting queued reports before beginning the timed run.
        device.set_nonblocking(1)
        deadline=time.perf_counter()+1
        while device.read(64) and time.perf_counter()<deadline:pass
        device.set_nonblocking(0)
        end=time.perf_counter()+a.seconds
        while time.perf_counter()<end:
            raw=bytes(device.read(64,100))
            now=time.perf_counter_ns()
            if not raw:continue
            try:decode(raw)
            except ValueError:invalid+=1;continue
            rows.append((now,raw))
    finally:device.close()
    if a.csv:
        with open(a.csv,'w',newline='') as f:
            w=csv.writer(f);w.writerow(['arrival_ns','report_hex'])
            w.writerows((t,b.hex()) for t,b in rows)
    try:result=summary(rows)
    except ValueError as e:p.exit(1,str(e)+'\n')
    result['invalid_reports']=invalid
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
