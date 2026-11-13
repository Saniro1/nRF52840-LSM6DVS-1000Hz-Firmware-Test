# Fix40: use the existing VQF runtime gyro-bias estimate for HID

User reports that fix39 acceleration is more stable. The next reported issue is
stationary gyro output around [-0.31, +0.44, +0.06] degrees/s. That screenshot is
not a full bias or temperature measurement. No board is attached here.

Fix40 retains fix39 acceleration and mappings, and subtracts the existing VQF
runtime bias from a private gyro copy before HID conversion. It also changes the
VQF rest-reference filter time constant for better single-precision behavior at
high sample rates. This is an experimental software repair, not a hardware-proven
solution for all drift or sustained 1000 USB reports/s.

## Files, warm-up and recovery

Branch: `ds4-fix40-gyro-bias`.
Use `releases/ds4-fix40/fix40-ds4-inverted.uf2` for the current inverted mounting.
Normal and handheld variants are also included. Preserve your recoverable fix39
UF2, double-reset into the established bootloader, and copy the matching fix40.
If enumeration or operation deteriorates, double-reset and restore fix39.
Recovery has not been physically retested here. Do not flash Arduino/web outputs.

After flashing, let the board warm up, then leave it completely untouched on a
rigid surface for at least 30 seconds so the runtime estimator can settle. Avoid
learning while deliberately rotating slowly. The time is a practical test interval,
not a promise of physical convergence. After warm-up, reset/re-run the host app's
GYRO calibration so it does not continue subtracting an old host-side drift offset.
A host's stored "Gyro Drift" field can remain nonzero until that recalibration.
Do not erase firmware physical gyro or six-face acceleration calibration.

The correction is active only with VQF selected. This firmware's upstream selection
is `sensor_fusion = 3` for VQF. Stored settings can override defaults. If needed,
use the existing serial shell to check `read_config sensor_fusion`, and select
`write_config sensor_fusion 3` followed by `reboot`. This is not required if VQF
is already active. Other fusion selections pass gyro through unchanged. No stored
setting is silently overwritten by the binary patch.

## Binary findings

Upstream reference: SlimeVR-Tracker-nRF cbfff16ebed1659d4c0e9f361ded0030fb66855a:
https://github.com/SlimeVR/SlimeVR-Tracker-nRF/blob/cbfff16ebed1659d4c0e9f361ded0030fb66855a/src/sensor/fusion/vqf/vqf.c
https://github.com/SlimeVR/SlimeVR-Tracker-nRF/blob/cbfff16ebed1659d4c0e9f361ded0030fb66855a/vqf-c/src/vqf.c

The stored physical gyro calibration runs at 0xa10c. The calibrated raw gyro is
then fed to fusion, and the custom converter at 0x99b8 sends that calibrated raw
value to HID. VQF's runtime estimate was not applied to this HID path. It was used
internally by fusion. Subtracting it from fusion input would feed the estimator
its own correction; fix40 therefore modifies only a temporary HID copy.

VQF function table is at 0x30970. Getter 0xbb58 uses state 0x200033b8 and branches
to 0x180c8. That function copies state offsets 0x5c, 0x60, 0x64, hence the bias
vector at 0x20003414. Source and compiled degree-to-radian update wrapper agree:
these bias values are radians/s. They must be multiplied by 180/pi before
subtraction from degree/s gyro data. The builder guards the getter, state-offset
instructions and dispatch table against the exact image.

The patch at 0x5486 operates only for valid gyro packets and only while the active
fusion pointer is that exact VQF table. It reads all three bias components, converts
units, and subtracts them from the three current calibrated gyro values on its
stack. If any component is nonfinite or outside VQF's existing +/-5 degrees/s bias
clip, the whole correction is skipped. This is validation of an estimator output,
not a motion deadzone. The original converter still performs int16 saturation.
The source gyro array, calibration, fusion inputs and stored settings are untouched.

No new estimator, persistent RAM, screenshot-derived offset, gyro deadzone or gyro
smoothing is added. Motion below one converter quantum (1/16 degree/s) is still
limited by the existing integer conversion; exact zero during real noisy operation
is not promised. The wrapper preserves integer registers, condition flags, FPU
registers/FPSCR and the prior interrupt state. It uses 64 temporary stack bytes;
the deepest existing converter path adds 24, for 88 bytes relative to the old call
site. Hardware stack and IRQ margins remain unmeasured. Bias reads/subtraction run
outside PRIMASK; VQF writes its estimate from the same sensor thread.

## Rest-reference numerical behavior and retained state

The embedded VQF uses single precision. Its configured restFilterTau is 1.114532 s.
Executing the actual compiled estimator at 1920 Hz on constant synthetic gyro and
gravity produced an inaccurate bias estimate. Fix40 changes only that reference
filter's time constant to 0.1 s. This is an estimator tuning parameter, not a
physical calibration offset. Original restMinT (about 2.587 s), motion thresholds,
bias clip and bias-update algorithms remain unchanged. A shorter reference filter
also changes motion/rest detection behavior; physical vibration performance is not
established by constant-input emulation.

Old retained fusion payloads contain old coefficients. The VQF load-table entry
is redirected to initialize volatile fusion using the payload's three saved sample
periods rather than restoring its old state and coefficients. This guarantees the
new reference parameter is used after a retained-state boot. Physical calibration
and settings live elsewhere and are not erased. Volatile bias and fusion orientation
relearn on every such load/restart; this also resets the fusion quaternion rather
than restoring the previous tracker orientation. This build targets USB gyro use.
It does not fix the older retained-payload behavior of reusing saved sample periods
if sensor ODR settings were changed between runs.

## Evidence and limits

New tests load the complete UF2 flash and .data initializer into Unicorn, execute
VQF initialization and the real compiled gyro/accel updates, and inject 20 seconds
of synthetic stationary input. All VQF math executes from the image; it is not a
Python estimator or a mocked bias getter. For raw bias (0.06, 0.31, -0.44) degrees/s
and acceleration (0, 0, 1) g, observed maximum bias-estimation errors were:

| Firmware | Simulated sensor rate | Maximum error after 20 s |
|---|---:|---:|
| fix39 | 1920 Hz | 0.070562 degrees/s |
| fix40 | 1920 Hz | 0.000792 degrees/s |
| fix40 | 120 Hz | 0.000531 degrees/s |

These are synthetic estimator errors, not measurements of the user's board.
Fix40's HID output quantized to zero for those constant inputs. A subsequent
100 degrees/s input change was retained, and a separate 0.125 degrees/s signal
was retained as two counts. Temperature drift, vibration, dynamic convergence and
actual rate/timing require physical testing. No new temperature model is claimed.

Seven new tests cover unit conversion, all three report mappings, source-array
preservation, small deliberate motion, invalid-bias/non-VQF/invalid-gyro fallbacks,
CPU/FPU/interrupt state, retained-load reinitialization, unchanged acceleration
batch publication and strict binary boundaries/hashes. The packet-test clock alone
is stubbed. The tests do not run Zephyr scheduling, USB hardware, SDL or FlexInput.

A six-axis IMU cannot distinguish all slow constant rotation from gyro bias, and
cannot observe absolute yaw. VQF can absorb sufficiently slow intentional motion
when it classifies that motion as rest. Remaining random noise and long-term yaw
drift are possible. Calibration is not a guarantee of zero output on every report.

Acceleration remains the fix39 valid-sample batch mean with fix38 LPF2, preserving
gravity and the normal (+Y,-Z,-X), inverted (-Y,-Z,+X), handheld (+Y,+X,-Z) mappings.
At nominal 6 ms collection there are about 167 new acceleration values/s. USB retry
remains 33 ticks; report timestamp is still report-build time. This build establishes
neither 1000 fresh motion samples/s nor measured 1000 USB reports/s.

## Reproduce

```sh
bash tools/setup_firmware_env.sh
export PATH="/workspace/toolchain/gcc-arm-none-eabi-9-2019-q4-major/bin:$PATH"
python tools/build_fix40.py
/workspace/toolchain/venv/bin/python -m unittest discover -s tests -v
```

All 36 host tests passed; all three UF2s and the manifest rebuilt byte-for-byte.
The builder composes exact guarded fix39 and verifies VQF ABI, call sites, parameter
bytes, erased caves and boundaries before patching. Hashes/parameters are in
`releases/ds4-fix40/manifest.json`. Older variants remain unchanged.
