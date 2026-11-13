# Fix39: calibrated acceleration batch mean

Experimental three-variant builds for Smol Slime nRF52840 + LSM6DSV. This continues
the authorized repair after fix38 produced only a slight user-reported improvement.
No physical board is available here. Noise reduction, calibration success, USB
stability and 1000 completed reports/s are not established by the host tests.

## Build to try

On branch `ds4-fix39-accel-batch-mean`, use:

* `releases/ds4-fix39/fix39-ds4-inverted.uf2` for the current inverted mounting.
* `releases/ds4-fix39/fix39-ds4-normal.uf2` for normal mounting.
* `releases/ds4-fix39/fix39-ds4-handheld.uf2` for handheld mounting.

Keep a recoverable previous UF2. Double-reset into the established bootloader and
copy only the matching UF2. If operation worsens or enumeration fails, double-reset
and restore the previous UF2. Bootloader recovery is not physically retested here.
The repository's unrelated Arduino and web-generator outputs are not used.

Keep stored settings and calibration unchanged for the first comparison. Let the
board settle and warm up before observing the same stationary screen. No CSV
capture or firmware calibration erasure is required. If ordinary host calibration
is needed, run its existing Start control with the board level and untouched.
The screenshot's absolute peak label includes residual offset and is not a noise
standard deviation; see STATIONARY_SCREEN_REVIEW.md. A constant offset will not
be removed by averaging, nor should firmware invent one from a single pose.

## Concrete change

The sensor loop already calibrates each valid acceleration record, copies it to a
fusion input, and accumulates three float sums and an acceleration-only count.
It later computes a persistent per-batch mean in g at 0x5492..0x54ba. The previous
custom HID converter call at 0x5486 instead publishes every individual sample,
leaving the latest processed sample in the HID acceleration array.

Fix39 uses the existing mean for HID acceleration:

1. At 0x547a, only the per-record HID acceleration-valid argument is suppressed.
   Gyro-valid handling, physical sensor calibration, fusion and accumulation remain.
2. After the existing nonzero-count guard and three floating-point divisions, a
   trampoline at 0xace00 completes the mean's last-axis store and calls the existing
   converter with gyro-valid=0, acceleration-valid=1, and the average's address.
3. The trampoline restores caller integer registers, APSR condition/Q flags,
   FPSCR and s12-s15, and resumes at 0x5006. The existing converter/PRIMASK wrapper
   publishes all three acceleration halfwords coherently. Report construction and
   the USB in-flight guard are unchanged.

Only valid acceleration records contribute to the denominator. Gyro-only records
are not treated as zero acceleration. A zero-acceleration-count batch leaves the
previous complete acceleration value intact. New motion changes the output on
the next completed nonempty batch; there is no stationary freeze or deadzone.

The average is computed after the existing calibration and before gravity removal.
All three axes and both gravity signs are retained. Upstream VQF and fusion_none
update_accel paths do not modify the input vector used by the existing accumulator.
Reference revision: SlimeVR-Tracker-nRF cbfff16ebed1659d4c0e9f361ded0030fb66855a.
The embedded accumulation/division instructions are executed in the new tests.

No new persistent RAM or guessed bias constants are allocated. The new call uses
48 bytes of temporary caller stack plus the existing converter wrapper's stack
(24 bytes on its deepest path), adding up to 72 bytes relative to the old average
store/branch path. Hardware stack margins have not been measured. The new mean
calculation itself is existing code; interrupt masking remains confined to the
existing short converter publication and report snapshot. No bus/Zephyr call is
added inside a new critical section.

The old converter invocation counter also increments once for the new mean
publication; it therefore has one extra conversion invocation per nonempty batch.
It is not the DS4 report counter or a sensor-ODR measurement. The DS4 six-bit
report counter and timestamps remain as in fix38.

## Noise and latency tradeoff

This is a finite batch average: every valid calibrated sample contributes equally.
It attenuates variation within the batch and changes motion response. It does not
prove the cause of the user's fluctuations. Low-frequency drift, vibration, static
bias, incorrect stored calibration or persistent communication faults can remain.
The preceding hardware LPF2 from fix38 remains enabled at actual acceleration
ODR/20. Its noise and phase behavior are not simulated by the tests.

The collection target is still 6 ms in low-noise mode. At uniform sampling, a batch
mean represents approximately the middle of its sample window, adding roughly
half a batch of sample age compared with the newest record. This is a nominal
tradeoff, not a measured latency bound. Runtime low-power states use longer
collection windows, and CPU/bus delays can extend them. When a batch contains one
acceleration sample, there is no averaging benefit.

Acceleration is published once per nonempty batch. Under nominal 6 ms collection,
that means approximately 167 new acceleration publications/s, even if USB reads
or repeated packets arrive faster. Gyro remains on the existing per-record path.
The DS4 timestamp is still report-build time, not the batch's midpoint time.
Fix39 does not establish 1000 fresh motion samples/s or 1000 USB reports/s; the
33-tick retry and other previous runtime/protocol limitations remain. This build
prioritizes the currently reported acceleration stability problem, with its loss
of temporal detail explicit.

Mappings remain unchanged on both sensors:

| Variant | Mapping |
|---|---|
| normal | +Y, -Z, -X |
| inverted | -Y, -Z, +X |
| handheld | +Y, +X, -Z |

## Reproduce and verify

```sh
bash tools/setup_firmware_env.sh
export PATH="/workspace/toolchain/gcc-arm-none-eabi-9-2019-q4-major/bin:$PATH"
python tools/build_fix39.py
/workspace/toolchain/venv/bin/python -m unittest discover -s tests -v
```

The builder composes exact guarded fix38, verifies the original sample-valid
instruction, count guard, complete mean calculation and mean-tail instructions,
checks the erased cave and emits all three hashes in manifest.json. Only those
two hook regions and the new cave may change relative to fix38.

Seven new tests execute actual Thumb/VFP code for calibration, per-record
accumulation, the nonzero-count branch, all three average divisions, patched
publication, converter and three-profile report construction. Fusion update is
replaced by a non-mutating no-op and the clock is stubbed for packet checks.
Coverage includes:

* All six gravity faces across all three mappings.
* Alternating synthetic input, contrasting fix38's latest sample with fix39's
  exact batch mean. This is arithmetic validation, not physical noise evidence.
* Existing calibration applied before the mean.
* Empty, single-sample and moving multi-axis batches.
* Mixed gyro/acceleration validity, acceleration-only sample counts, and retained
  fresh gyro values during acceleration averaging.
* Integer/FPU/condition/interrupt state preserved at the rejoin boundary compared
  with executing the original mean-tail code.
* Hashes, erased cave and strict binary change boundaries; original calibration,
  converter, FIFO reader and packet code remain byte-identical.

All 29 host tests passed. All three UF2s and the manifest rebuilt byte-for-byte.
Older fix35 through fix38 tests continue to run. None of these run Zephyr, NVIC,
physical sensor/FIFO/filter, actual USB, SDL or FlexInput. Physical improvement
still requires the user's normal board test; no stationary capture is requested
as a prerequisite for these software changes.
