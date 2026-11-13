import sys
from pathlib import Path
import struct
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from measure_ds4 import decode, summary

class CaptureTests(unittest.TestCase):
    def test_measured_rates_and_units(self):
        for period,hz in ((1000000,1000),(5000000,200)):
            rows=[]
            for i in range(1001):
                b=bytearray(64);b[0]=1;b[7]=(i%64)<<2
                struct.pack_into('<H',b,10,i&65535)
                struct.pack_into('<h',b,13,16384);struct.pack_into('<h',b,23,8192)
                rows.append((i*period,bytes(b)))
            r=summary(rows)
            self.assertAlmostEqual(r['arrival_hz'],hz)
            self.assertAlmostEqual(r['gravity_mean_g'],1)
            self.assertAlmostEqual(r['gyro_mean_dps'][0],16384/16)
            self.assertEqual(r['counter_discontinuities'],0)
    def test_stationary_axis_noise_retains_gravity(self):
        rows=[]
        for i,offset in enumerate((-8,8,-8,8)):
            packet=bytearray(64);packet[0]=1
            struct.pack_into('<3h',packet,19,offset,-8192,0)
            rows.append((i*1000000,bytes(packet)))
        result=summary(rows)
        self.assertEqual(result['accel_mean_g'],[0,-1,0])
        self.assertEqual(result['accel_stddev_g'],[8/8192,0,0])
        self.assertEqual(result['accel_peak_to_peak_g'],[16/8192,0,0])
        self.assertGreaterEqual(result['gravity_mean_g'],1)

    def test_invalid_reports_do_not_pass(self):
        for b in (b'',b'\x01'*65,b'\x00'*64):
            with self.assertRaises(ValueError):decode(b)
        with self.assertRaises(ValueError):summary([])

if __name__=='__main__':unittest.main()
