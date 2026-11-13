# Fix38: experimental acceleration bandwidth limit

The user's fix37 screenshot still shows stationary Accel X/Y fluctuations, with
an acceleration peak label approximately ±0.0327 g (±0.32 m/s²). That label is not
an RMS measurement, a spectrum, or evidence of the source of the noise. Fix37
has not solved the reported symptom.

Fix38 adds the LSM6DSV's hardware accelerometer LPF2. This is an explicit filtering
experiment, not a confirmed noise-source repair. It reduces acceleration bandwidth
and adds lag. It cannot be used as proof that bus faults, vibration or calibration
problems are absent. No board was attached during development.

## Download and try

Use `releases/ds4-fix38/fix38-ds4-inverted.uf2` on branch
`ds4-fix38-accel-lpf-test` for the current inverted mounting. Normal and handheld
files are also present. All three retain the requested gyro/acceleration mappings.

Preserve a recoverable previous UF2, double-reset into the established bootloader,
and copy only the matching UF2. If operation deteriorates or the controller stops
enumerating, double-reset and restore the previous UF2. Recovery has not been
physically retested. The unrelated Arduino/web-demo images remain unsuitable.

Keep existing settings/calibration for the comparison. Let startup settle and warm
up before using the same stationary calibration screen. No host CSV capture or
calibration erasure is required. Gyro behavior should remain as in fix37; acceleration
responds more slowly. Do not interpret a quieter graph as proof of physical accuracy.
If acceleration still fluctuates substantially, this experiment has not solved it.

## Evidence and design

Reference: ST AN5922 Rev 3, accelerometer composite-filter diagram and Table 17,
and ST's LSM6DSV register driver. The filter diagram feeds the FIFO as well as the
normal output registers. Bit layout was checked against the official header:
https://www.st.com/resource/en/application_note/an5922-lsm6dsv-6axis-imu-with-embedded-sensor-fusion-i3c-oiseis-for-smart-applications-stmicroelectronics.pdf
https://github.com/STMicroelectronics/lsm6dsv-pid/blob/ba9ea4ea331184416c0be47616e64a51200f0c23/lsm6dsv_reg.h

AN5922 PDF SHA-256 inspected:
898b8a8340a185eb4f2240dd5028a40a2826e3ef0f7570f173df7b4281b8b210.

The embedded LSM6DSV initializer at 0xf328 writes only full-scale selection to
CTRL8 (0x17) and never enables LPF2 in CTRL9 (0x18). The upstream reference named
in the firmware does the same. Reset leaves the optional LPF2 disabled; actual
registers on the user's board have not been read back. Unfiltered acceleration
has nominal bandwidth ODR/2 in high-performance operation. This leaves substantial
high-frequency content available to the current per-sample HID path.

Fix38 hooks the CTRL8 write at 0xf35c and:

* Preserves the selected full scale and sets HP_LPF2_XL_BW=010 (CTRL8 |= 0x40).
* Reads CTRL9, sets LPF2_XL_EN (bit 3) and clears the high-pass selection and
  high-pass reference bits (4 and 6). Other CTRL9 bits are preserved.
* Skips the CTRL9 write if its read fails, combines all I/O errors, and resumes
  the original initializer's error handling. No new interrupt mask is used.

The selected bandwidth is **actual acceleration ODR / 20**. It is nominally 96 Hz
at 1920 Hz sensor ODR, 48 Hz at 960 Hz, and 6 Hz at 120 Hz. Saved ODR settings and
runtime power modes still apply; this is not a fixed 96 Hz filter and can become
sluggish at low ODR. This ratio is an engineering test choice, not a measured
optimum for this board. Physical attenuation and group delay have not been measured.

ST specifies up to 21 samples for this filtering configuration to settle; startup
or ODR/power-mode transitions must not be treated as steady-state data. Settling
time is not the same as group delay. The patch does not add a warm-up discard
counter. DRDY_MASK is left unchanged: enabling it would introduce special FIFO
settling values that the existing decoder does not explicitly reject. This remains
a limitation, particularly during runtime mode transitions.

The filter has DC response, so gravity and sustained acceleration remain. There is
no resting offset subtraction, deadzone, per-axis clipping change or HID smoothing.
The physical calibration and fusion paths also receive the filtered acceleration;
filter phase lag can therefore affect fusion and motion response, not just the graph.
The gyro path and all fix37 repairs remain unchanged.

USB retry is still 33 ticks and collection interval 6 ms. The endpoint still says
1 ms; neither bandwidth changes nor this descriptor establish 1000 reports/s.
The full DS4 protocol and physical calibration limitations documented in
DS4_FIX36.md and DS4_FIX37.md continue to apply.

## Reproduce and validation scope

```sh
bash tools/setup_firmware_env.sh
export PATH="/workspace/toolchain/gcc-arm-none-eabi-9-2019-q4-major/bin:$PATH"
python tools/build_fix38.py
/workspace/toolchain/venv/bin/python -m unittest discover -s tests -v
```

Builder composes the exact guarded fix37 build, checks the original call instruction
and erased flash cave, and writes hashes and settings to manifest.json. Tests execute
the real new Thumb wrapper with mocked bus calls for every full-scale selection and
all 256 prior CTRL9 bytes (1024 combinations), I/O failures, ABI register/stack and
interrupt-state preservation. Only the initializer hook and cave may differ from
fix37; report code, calibration, FIFO decoder and gyro converter stay byte-identical.

All 22 host tests passed; all three UF2s and the manifest reproduced byte-for-byte.
These tests confirm requested register transactions and software boundaries. They
do not simulate the analog sensor/filter, measure noise reduction, or run a USB
host/Zephyr/SDL. A hardware improvement or solved calibration is not claimed.
