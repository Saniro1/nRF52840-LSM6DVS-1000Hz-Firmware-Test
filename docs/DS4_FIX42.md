# Fix42: DS4 HID 1000 reports/s scheduling candidate

The user confirms fix41 motion behavior is working and requests full 1000 Hz on
the DS4 HID path. Fix42 changes USB report scheduling and submission-error recovery
only. It preserves the tested acceleration, gyro bias correction, 0.10 degrees/s
soft deadzone and all three mappings. No board is attached to this environment:
**1000 actual USB reports/s is the target, not a measured result here.**

## Download and try

Branch: `ds4-fix42-usb-1000hz`.

* `releases/ds4-fix42/fix42-ds4-inverted.uf2` — current inverted mounting.
* `releases/ds4-fix42/fix42-ds4-normal.uf2` — normal.
* `releases/ds4-fix42/fix42-ds4-handheld.uf2` — handheld.

Keep a recoverable fix41 UF2. Double-reset into the established bootloader, copy
the matching fix42, and use the same host and settings for comparison. No new shell
configuration is required for the USB retry change. If operation deteriorates or
fails to enumerate, double-reset and restore fix41. Recovery is not newly
hardware-tested. Do not use Arduino or web-generator outputs from this repository.
Keep the VQF selection, warm-up and host gyro calibration instructions from fix40.
There is no need to erase physical calibration to change the report retry interval.

## Findings and actual changes

The image's DS4 HID interrupt-IN endpoint already advertises full-speed 1 ms polling:
flash 0x3a783 contains `07 05 80 03 40 00 01` before dynamic endpoint allocation.
The descriptor's endpoint placeholder is handled by the existing Zephyr composite
stack; the patch does not invent a new endpoint. Device identity remains Sony
054c:05c4. The DS4 report is still report ID 1 and exactly 64 bytes, with gyro,
acceleration, six-bit counter, real-clock timestamp and connected/status fields.

The sender acquired an atomic in-flight guard, built a report, submitted 64 bytes,
then slept for 33 ticks of its 32768 Hz clock. That is already about 1.007 ms BEFORE
processing/scheduling overhead, so an endpoint advertising 1 ms did not establish
1000 completed reports/s. Kernel code 0x2a12c consumes the timeout as ticks; wrapper
0x2a20c converts the returned remaining time, rather than changing input to ms.

Fix42 changes the timeout immediate at 0x991c from 33 to 8 ticks (nominally 244 us).
This gives several requeue opportunities per USB frame after the prior report
completes. It does not force the USB host to poll faster than 1 ms. Tick alignment,
interrupt latency and work/scheduler delays add time; this is not a hard timing
bound or proof that every host frame is filled. Nonzero sleeps still allow the
lower-priority sensor thread to run. Faster retries can increase wakeups/CPU use;
real sensor/USB runtime stability has not been established here.

A second problem was independently verified in the full report loop: after an
unsuccessful HID submission, the code logged an error but retained its guard.
Without an accepted transfer, there is no completion owed to clear that guard;
subsequent iterations skip report construction indefinitely. This can stall HID
without an actual USB disconnect. It does not prove this caused any user's prior
symptoms.

Fix42 hooks the existing error-only path at 0x986c. It atomically clears only guard
bit 0 with barriers, retaining other flag bits and the original error logging.
It then replays the original allocator call and resumes at 0x9872. On successful
submission, ownership stays with the existing completion callback at 0x9748.
An accepted report is never rebuilt while that callback is outstanding. The patch
adds no stack frame and does not move report construction into an ISR.

The recovery relies on the existing API contract: a nonzero submission result means
that attempt was not accepted. It does not introduce a timeout that could release
a still-owned DMA buffer. Reset/abort paths that fail to deliver completion for a
previously accepted transfer remain dependent on the existing USB stack behavior.
The report counter advances on report construction, so a failed submission can
leave a visible counter gap; that diagnostic evidence is not hidden.

## Report rate versus motion freshness

This change targets **DS4 USB reports**, not just an IMU setting or an advertised
interval. A 64-byte report can be sent every host polling frame even when its
motion fields repeat. Sensor collection remains at the user-tested nominal 6 ms
interval, and acceleration retains the fix39 mean, about 167 new acceleration
publications/s under nominal operation. Gyro continues to be processed per valid
FIFO gyro record, then exposed through the latest complete published value.
Thus even measured 1000 USB reports/s would not establish 1000 fresh six-axis
samples/s. Fix42 does not change ODR, collection timing or acceleration filtering
to make repeated reports look like new sensor samples.

DS4 timestamp remains derived from the real 32768 Hz clock in 16/3 us units; it is
report-build time, not a fictional fixed 1000 Hz increment or FIFO sample time.
Host sensor metadata, UI refresh rates and changed-value counts can differ from
raw HID report throughput. SDL's nominal DS4 sensor metadata may not reflect the
custom device's actual USB report rate. Count real report arrivals to assess HID
throughput; bus-level 1 ms completion requires USB trace evidence.

## Verification

Five new tests execute the complete compiled report loop beginning at 0x9770,
including guard acquisition, memset, real patched DS4 builder, submit/error path,
clock arithmetic and retry setup. They also execute the actual completion callback.
USB submission, kernel clock and logging are mocked; Zephyr scheduling, USB host
polls and physical hardware are not emulated.

Coverage:

* Failed submission reproduces a retained-guard stall in fix41; fix42 releases it
  and submits again. Repeated error statuses recover and diagnostics remain.
* A delayed completion leaves the guard set and the in-flight 64-byte buffer
  byte-identical across repeated retries, including changing sensor arrays.
* 3000 complete virtual DS4 submission/completion cycles across the three profiles
  verify report ID, length, connected state, mapping, counter and actual-clock
  timestamp arithmetic. Virtual frame timestamps are supplied by the test; this
  is NOT a 1000 Hz hardware measurement.
* The 1 ms HID endpoint and Sony DS4 identity are checked. Hashes and changes are
  confined to the retry immediate, error hook and erased recovery cave.
* Motion/calibration/filter/bias/deadzone code is byte-identical to fix41.

## Reproduce and optional physical measurement

```sh
bash tools/setup_firmware_env.sh
export PATH="/workspace/toolchain/gcc-arm-none-eabi-9-2019-q4-major/bin:$PATH"
python tools/build_fix42.py
/workspace/toolchain/venv/bin/python -m unittest discover -s tests -v
```

All 45 host tests passed; all three UF2s and the manifest rebuilt byte-for-byte.
Each profile's hash and retry parameters are in manifest.json. The manifest keeps
hardware_validated=false and usb_rate_measured=false. The original fixes/builds
remain available.

If raw throughput measurement is wanted on the connected host, the existing tool
counts actual 64-byte HID reports independently of motion changes:

```sh
python tools/measure_ds4.py --list
python tools/measure_ds4.py --device INDEX --seconds 60 --csv fix42.csv
```

This optional capture is not required to flash/test and is not being demanded from
the user. Its arrival_hz includes host buffering/scheduling effects. USBPcap/usbmon
or a USB analyzer can establish bus-level transactions. Physical acceptance remains
sustained approximately 1000 completed reports/s, bounded gaps, correct motion and
no reconnects/stalls over minutes. Those results cannot be certified in the cloud.
