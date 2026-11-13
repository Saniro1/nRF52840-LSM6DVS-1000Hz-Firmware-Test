# JSM calibration project – progress log

Goal: make the Smol Slime (SuperMini nRF52840 + single LSM6DSV) work properly with
JoyShockMapper by porting the calibration ideas from
[DGB-SOURCE-CODE-JSM](https://github.com/Saniro1/DGB-SOURCE-CODE-JSM) (dual BMI160, RP2040)
to a single-IMU design.

| # | Step | Status |
|---|------|--------|
| 1 | Inspect both repos + both UF2 files, record findings | done |
| 2 | Find why aim "bounces" on `CURRENT_1.UF2` – gyro/accel report swap identified and patched | done; user reports improvement |
| 2.1 | Diagnose X/Y mapping | done: user confirmed left/right drives vertical aim and up/down drives horizontal aim |
| 2.2 | Apply X/Y axis swap to the tested UF2 | `build/CURRENT_1_gyro-accel-fix2.UF2` generated and committed; user reports improved mapping but horizontal X sign was reversed |
| 2.3 | Correct gyro direction signs / yaw-roll mapping | fix6 is the working direction baseline; `build/CURRENT_1_gyro-accel-fix7.UF2` swaps X/Z report sources as a yaw-versus-roll candidate; hardware test pending |
| 3 | Specify the DGB calibration algorithm precisely (and its flaws) | pending |
| 4 | Design single-IMU calibration (bias, stationary detect, auto-recal) | pending |
| 5 | Implement calibration core (pure C) + host tests | pending |
| 6 | Implement LSM6DSV scaling / axis map / DS4 report for JSL | pending |
| 7 | Zephyr app + board definition + CI workflow | pending |
| 8 | Get CI green, produce .uf2 | pending |
| 9 | Flash/test guide, recovery paths, JSM config tuning | pending |
| 10 | Final docs, release, cleanup | pending |

See `docs/STEP1_ANALYSIS.md`, `docs/STEP2_ROOT_CAUSE.md`, `docs/STEP2_1_AXIS_MAPPING.md`, and `docs/STEP2_3_X_SIGN.md`.
See `docs/STEP1_ANALYSIS.md` and `docs/STEP2_ROOT_CAUSE.md`.

## Side task (Oct 23): orientation
`testing/` holds fix16 (from user), fix17 and fix17-alt (IMU rotated 90° about yaw). Built by `tools/make_fix17.py`. Needs hardware test.

fix17 test result: pitch inverted, yaw dead, roll ok (JSM LOCAL ignores Z slot) -> axes re-derived; fix18 / fix18-alt added (`tools/make_axis_variant.py`).


## Test repository follow-up: fix35

Imported the branch through ef47e4c into nRF52840-LSM6DVS-1000Hz-Firmware-Test.
Added guarded builds for normal/inverted/handheld, DS4 timestamp and scale corrections,
saturation, handedness correction for handheld, 1ms active sensor batching and faster
USB queue retries. ARM emulation and capture-analysis tests pass locally. Existing
calibration machinery is retained; new gyro bias algorithms/source rebuild remain
unfinished. Hardware calibration and measured 1000Hz throughput are pending.
See [DS4_FIX35.md](DS4_FIX35.md) for evidence and limitations.

## Fix36 independent review

See DS4_FIX36.md for the SDL unit discrepancy, descriptor feature gap, clock/ABI
and shared-buffer audit, conservative three-variant diagnostic builds and open
hardware requirements. No reset/noise root cause or 1000 Hz result is claimed.

## Fix37 continued independent repair

Recovered upstream reference cbfff16ebed1659d4c0e9f361ded0030fb66855a and matched
compiled LSM6DSV FIFO paths. Added guarded rejection of failed FIFO reads and
coherent converter publication/report snapshots. See DS4_FIX37.md for executed
failure-injection tests, limitations and recovery. Physical noise remains unverified.

## Fix38 acceleration bandwidth experiment

Fix37 stationary acceleration remains noisy in the user's screenshot. Added a
separate LSM6DSV hardware LPF2 ODR/20 test build, preserving gravity and all mappings.
See DS4_FIX38.md for source references, latency/settling tradeoffs and limitations.
No physical noise reduction, calibration success or 1000 Hz result is claimed.

## Fix39 acceleration batch mean

After user-authorized continuation, route the existing calibrated FIFO batch mean
to HID acceleration instead of publishing each individual acceleration record.
Keep gyro behavior, gravity, mappings and prior fixes. Tests execute accumulation,
calibration, averaging and publication. See DS4_FIX39.md for the explicit roughly
6 ms window/167 Hz nominal acceleration-publication tradeoff. Physical noise and
1000 Hz remain unverified.

## Fix40 gyro runtime bias correction

User reports fix39 acceleration is more stable and requests stationary gyro-drift
repair. Route the existing VQF estimate (rad/s) into a private degree/s HID gyro
copy. Address high-rate single-precision rest-reference behavior with a 0.1 s
reference filter; reinitialize retained volatile VQF state so old coefficients
cannot override it. Physical calibration and fix39 acceleration are retained.
Actual compiled VQF convergence is tested with synthetic 120/1920 Hz inputs.
See DS4_FIX40.md for results, slow-rotation/retained-state tradeoffs and limits.
