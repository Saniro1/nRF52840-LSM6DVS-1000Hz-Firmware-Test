# Fix37: FIFO error rejection and coherent sensor handoff

Experimental binary patches for the same Smol Slime nRF52840 + LSM6DSV board.
No physical board is attached to this environment. Fix36 did not resolve the
reported stationary acceleration noise. Fix37 repairs two independently
identified software failure paths; their contribution on this board is unmeasured.
This is not a verified noise/calibration fix or a 1000 Hz release.

## Download and recovery

Builds are in `releases/ds4-fix37/` on branch `ds4-fix37-diagnostic`.
Start with `fix37-ds4-inverted.uf2` for the currently used inverted mounting.
Normal and handheld builds are also included; all three retain the requested
mappings on both gyro and acceleration:

| Variant | Output axes |
|---|---|
| normal | +Y, -Z, -X |
| inverted | -Y, -Z, +X |
| handheld | +Y, +X, -Z |

Use the established double-reset bootloader procedure and copy the appropriate
UF2 to the bootloader drive. Preserve a previously recoverable UF2 first. If
fix37 fails to enumerate or behaves worse, double-reset back into the bootloader
and restore that UF2. Bootloader recovery is not newly hardware-tested here.
Do not use the repository's unrelated Arduino or web-generator firmware.

No calibration reset, new user settings or host capture is required to try this
build. Existing stored settings/calibration are retained. Keep settings unchanged
for a useful comparison. Do not erase good calibration. On a rigid stationary
surface, check whether the previous spikes/noise and reconnects persist. Only
attempt calibration after operation is stable: warm up, run the existing serial
`calibrate` and `6-side` prompts if needed, and accept only explicit success.
Gravity should remain approximately 1 g, not zero. Testing a build is optional;
there is no claim that the existing SDL Noise Progress failure is solved.

## Findings supported by actual binary execution

### FIFO bus errors returned valid-looking packet counts

Upstream source revision identified inside the image is SlimeVR-Tracker-nRF
`cbfff16ebed1659d4c0e9f361ded0030fb66855a`. It was checked out independently:
https://github.com/SlimeVR/SlimeVR-Tracker-nRF/blob/cbfff16ebed1659d4c0e9f361ded0030fb66855a/src/sensor/imu/LSM6DSV.c

This is an upstream reference, not recovered source for the custom USB changes.
The compiled LSM6DSV function table at flash 0x30adc contains FIFO reader 0xf54d
and decoder 0xf0dd (Thumb pointers). Decoder 0xf0dc handles seven-byte tagged
records: tag >> 3 of 2 means acceleration, 1 means gyro; other tags return invalid.
Both paths sign-extend little-endian int16 axes and multiply by runtime sensitivity.
The executed decoder agrees with this source. No demonstrated axis-byte swap or
acceleration unit mismatch was found in these paths.

Reader 0xf54c reads count, caps it to buffer length / 7, reads records, combines
SSI error results at 0xf5c4 and branches to logging on failure. It then returns
r4 (the count) even when an SSI call failed. The caller allocates a FIFO buffer
and processes the returned count. Incomplete/unwritten bytes may therefore be
interpreted as records. Whether bus errors occur on the user's board is unknown.

Fix37 hooks 0xf5e8 only on that error-logging path. It sets r4=0, replays the
original r2=0x1840 logger argument, then resumes the original log call at 0xf5ec.
Successful reads and existing diagnostics are unchanged. This rejects the whole
failed batch; it does not claim to resynchronize the hardware FIFO after a partial
transfer or eliminate the underlying communication error. Persistent failures
still follow the original sensor-error handling and need hardware diagnosis.

### In-place sensor arrays had no coherent publication/snapshot

Converter 0x99b8 writes gyro and acceleration as individual halfwords. The USB
report cave reads these same arrays one axis at a time. The USB in-flight guard
protects the 64-byte report buffer, not these arrays. In a single-core preemption
model, there are valid schedules in which an observer sees a partially updated
array or a report includes axes from different publications.

Fix37 wraps the existing pure converter with saved/restored PRIMASK. Both false
and true validity flags retain their original meaning: unavailable sensor data
is not replaced by zeros. The converter does not call Zephyr or access buses.
The report builder separately copies all six halfwords to 12 bytes on its stack
under saved/restored PRIMASK, restores interrupts immediately, and constructs the
report from that snapshot. Clock reading, packet construction and USB submission
remain outside this new reader critical section. No shared RAM is allocated.
The writer adds 16 bytes to its previous stack depth; the reader adds 24 bytes.

PRIMASK blocks ordinary interrupts, including scheduling, on this single-core
Cortex-M4. Prior disabled state is restored rather than blindly enabling IRQs;
BASEPRI is not changed. The tested writer path has 100 masked instruction edges.
This is NOT a wall-clock latency measurement or proof of acceptable interrupt
latency. NMI/HardFault and DMA are not serialized by PRIMASK; no writer from those
contexts was established. Hardware interrupt/stack margins remain unverified.

This does not synchronize the IMU's independent gyro and acceleration sample
times. At different ODRs, latest complete gyro and latest complete acceleration
are naturally different ages. Nor does it filter the sensor's genuine noise.

## What stays as in fix36

Gravity, sensor calibration, mappings, saturation, DS4 report timestamp and status
fields remain. Gyro output is 16 counts/dps for SDL's nominal DS4 interpretation;
acceleration remains 8192 counts/g. There is no gyro/acceleration deadzone, smoothing,
invented calibration constant, changed sensitivity, or temperature model.
Collection remains 6 ms and USB retries 33 ticks. Complete DS4 feature-report
compatibility and sustained 1000 Hz remain unresolved. See DS4_FIX36.md for those
protocol limitations and the distinction between report time and sensor time.

## Reproduce and verify

```sh
bash tools/setup_firmware_env.sh
export PATH="/workspace/toolchain/gcc-arm-none-eabi-9-2019-q4-major/bin:$PATH"
python tools/build_fix37.py
/workspace/toolchain/venv/bin/python -m unittest discover -s tests -v
```

All 19 host tests passed. Exact base SHA, original instructions, erased cave space and patch boundaries
are guarded. All three builds and parameters have SHA-256 hashes in manifest.json.
Rebuilding must produce identical UF2 and manifest bytes. The base and previous
fix35/fix36 artifacts remain untouched.

Tests execute the real patched report and converter instructions, not a rewritten
Python implementation of the converter. They cover 3018 fix37 report vectors,
all mappings and int16 edges, clock rollover, register/stack boundaries, prior
interrupt state, both independent sensor validity flags and unchanged no-data
values. Earlier fix35/fix36 suites also run.

800 adversarial report schedules inject a complete publication at every tested
instruction edge and defer it when PRIMASK is set. Fix36 produces mixed reports
in 33 schedules; fix37 produces none. A separate observer placed at each converter
instruction edge sees partial publications in fix36 and none in fix37. These are
controlled schedules that demonstrate the race and the repair under the stated
single-core model; they do not establish its physical frequency or noise impact.

The actual compiled FIFO reader is executed with mocked SSI/log calls for success,
status-read errors, data-read errors, combined errors, zero packets, capped batches
and maximum count. Fix36 returns a positive count on failed nonempty reads; fix37
returns zero. The real FIFO decoder is tested across all 32 tag values, low tag
bits, several record indices, signed limits and nominal physical units.

Unicorn does not run Zephyr scheduling, NVIC, sensor buses, the FIFO hardware, a USB
controller or SDL. Real noise, USB resets, stack/IRQ timing, temperature effects,
physical calibration and sustained throughput are unverified. No further captures
are requested from the user as a prerequisite for this software investigation.
