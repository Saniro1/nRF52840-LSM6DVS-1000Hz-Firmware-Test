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
