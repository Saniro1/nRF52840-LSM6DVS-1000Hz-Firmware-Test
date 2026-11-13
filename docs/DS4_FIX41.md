# Fix41: requested 0.10 degrees/s gyro deadzone

Fix40 had no gyro deadzone. At the user's explicit request, fix41 adds a **0.10
degrees/s soft deadzone on each gyro axis**, after VQF bias correction when active,
and before the existing conversion to 16 integer counts/degree/s.

For each corrected gyro component x in degrees/s:

```
abs(x) <= 0.10:  output = 0
otherwise:      output = sign(x) * (abs(x) - 0.10)
```

This is a soft deadzone: it reduces the magnitude of larger motion by 0.10 degrees/s.
It affects small intended motion as well as residual drift. It is not a change to
the physical sensor calibration, VQF's estimator input or stored calibration.
No acceleration deadzone is added. Gravity, fix39 acceleration averaging, fix38
hardware acceleration filter, fix40 bias correction and all three mappings remain.

## Download

Branch: `ds4-fix41-gyro-dz010`.

* `releases/ds4-fix41/fix41-ds4-inverted.uf2` — current inverted mounting.
* `releases/ds4-fix41/fix41-ds4-normal.uf2` — normal.
* `releases/ds4-fix41/fix41-ds4-handheld.uf2` — handheld.

Keep a recoverable previous UF2, double-reset into the established bootloader and
copy the matching file. Restore the previous UF2 through the bootloader if needed.
Recovery is not newly hardware-tested. Do not flash Arduino or web-demo outputs.

For VQF correction, the existing `sensor_fusion = 3` setting and warm-up/stationary
learning procedure from DS4_FIX40.md still apply. The deadzone also applies when
another fusion is selected and gyro passes through without VQF correction.
Existing host-side gyro offsets should be rechecked/recalibrated after firmware
changes; do not erase physical firmware calibration just to apply this deadzone.

## Implementation and quantization

The patch replaces the converter's gyro float load at 0x99ce with a jump to a new
cave at 0xace40. It replays the load/pointer increment, applies the float threshold,
restores s0/s1, and resumes at 0x99d2 for the original scaling and saturation.
This avoids approximating 0.10 degrees/s by one or two raw integer counts. Fusion
and calibration arrays are not modified. Acceleration-only publications skip this
path. The cave adds 8 bytes of temporary stack inside the existing converter
critical section; IRQ latency and stack margins remain physically unmeasured.

The final HID encoding still has 0.0625 degrees/s steps and truncates toward zero.
Consequently small nonzero results after the soft deadzone can also quantize to
zero. For example, corrected input 0.15 degrees/s becomes 0.05 before conversion,
which encodes as zero; 0.20 becomes 0.10, which encodes as one count (0.0625).
The nominal float threshold itself is 0.10, not 0.125.

## Reproduce and validation

```
bash tools/setup_firmware_env.sh
export PATH="/workspace/toolchain/gcc-arm-none-eabi-9-2019-q4-major/bin:$PATH"
python tools/build_fix41.py
/workspace/toolchain/venv/bin/python -m unittest discover -s tests -v
```

Builder composes exact guarded fix40, checks the displaced instruction and erased
cave, and emits hashes/parameters in manifest.json. Four new tests execute actual
Thumb/VFP instructions for threshold/sign/quantization behavior, bias-before-deadzone
ordering, all profile mappings, source preservation, acceleration output, stack/FPU
and IRQ state. Binary changes relative to fix40 are confined to the gyro-load hook
and new cave. Earlier builds/tests remain unchanged.

All 40 host tests passed; all three UF2s and the manifest reproduced byte-for-byte.
These are host tests. Physical residual drift, aiming feel, USB runtime stability,
calibration success and sustained 1000 Hz have not been measured here. The prior
6 ms batch/nominal ~167 Hz acceleration-publication tradeoff also remains.
