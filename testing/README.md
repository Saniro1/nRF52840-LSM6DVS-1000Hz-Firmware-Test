# testing/ – experimental UF2 builds (Smol Slime, DualSense-emulating SlimeVR build)

Flash: double-tap reset → drag the .uf2 onto the drive. Recovery: double-tap reset and flash
`../CURRENT.UF2` (stock SlimeVR) again. The bootloader is never touched.

| file | what it is |
|---|---|
| `CURRENT_1_gyro-accel-fix16-gyro-sign-preserved.uf2` | your fix16 (gyro/accel slots swapped + axis tweaks). Works with the IMU pointing **left**. |
| `CURRENT_1_gyro-accel-fix17.uf2` | fix16 + 90° yaw re-orientation so it works with the pad held **normally** (IMU pointing at the TV). Report = `(-Gy, -Gx, -Gz)` for gyro and accel. |
| `CURRENT_1_gyro-accel-fix17-alt.uf2` | same but turned the other way (`(+Gy, -Gx, +Gz)`). Use only if fix17 has **pitch (up/down) inverted**. |

| `CURRENT_1_gyro-accel-fix18.uf2` | After testing fix17: pitch inverted, yaw dead, roll fine. Axes re-derived: pitch=Gy, yaw=Gz, roll=Gx. Report = `(+Gy, -Gz, -Gx)` for gyro and accel. |
| `CURRENT_1_gyro-accel-fix18-alt.uf2` | same axes, yaw and roll signs flipped `(+Gy, +Gz, +Gx)`. Use only if fix18 yaw (turn left/right) goes the wrong way. |
| `CURRENT_1_gyro-accel-fix19.uf2` | fix18 + HID endpoint polling interval set to 1 ms (was 0 = invalid for full-speed USB). Same axes as fix18. |
| `CURRENT_1_gyro-accel-fix20-deadzone-0.25dps.uf2` | fix19 + soft gyro deadzone of 0.25 °/s (4 LSB). Smallest step. |
| `CURRENT_1_gyro-accel-fix20-deadzone-0.5dps.uf2` | fix19 + soft gyro deadzone of 0.5 °/s (8 LSB). **Try this first.** |
| `CURRENT_1_gyro-accel-fix20-deadzone-1.0dps.uf2` | fix19 + soft gyro deadzone of 1.0 °/s (16 LSB). Use if 0.5 still drifts. |
| `CURRENT_1_gyro-accel-fix21-normal.uf2` | **Chosen build, USB-C facing UP.** Identical to fix20 with the 1.0 °/s deadzone. Report `(+Gy, -Gz, -Gx)`. |
| `CURRENT_1_gyro-accel-fix21-inverted.uf2` | Same build for the board turned 180° so USB-C faces DOWN (rotated in its own plane, 180° about the sensor X axis). Report `(-Gy, +Gz, -Gx)`. |
| `CURRENT_1_gyro-accel-fix22-normal.uf2` | Same as fix21-normal (USB-C UP, 1.0 °/s deadzone). |
| `CURRENT_1_gyro-accel-fix22-inverted.uf2` | **USB-C DOWN**, corrected after testing fix21-inverted (pitch was right, left/right reversed). Report `(-Gy, -Gz, +Gx)`, i.e. 180° about the sensor Z axis. Use this one instead of fix21-inverted. |

| `CURRENT_1_gyro-accel-fix23-normal-deadzone-0.25dps.uf2` | USB-C UP (normal), soft gyro deadzone 0.25 °/s. |
| `CURRENT_1_gyro-accel-fix23-normal-deadzone-0.5dps.uf2` | USB-C UP (normal), soft gyro deadzone 0.5 °/s. |
| `CURRENT_1_gyro-accel-fix23-normal-deadzone-1.0dps.uf2` | USB-C UP (normal), soft gyro deadzone 1.0 °/s. |
| `CURRENT_1_gyro-accel-fix23-inverted-deadzone-0.25dps.uf2` | USB-C DOWN (inverted), soft gyro deadzone 0.25 °/s. |
| `CURRENT_1_gyro-accel-fix23-inverted-deadzone-0.5dps.uf2` | USB-C DOWN (inverted), soft gyro deadzone 0.5 °/s. |
| `CURRENT_1_gyro-accel-fix23-inverted-deadzone-1.0dps.uf2` | USB-C DOWN (inverted), soft gyro deadzone 1.0 °/s. |


**Current good builds: `fix23-normal-*` (USB-C up) and `fix23-inverted-*` (USB-C down), in 0.25 / 0.5 / 1.0 °/s deadzone.** fix24 (inverted with roll flipped) was tested and rejected, so it was removed. fix21/fix22 inverted are superseded by fix23.

## fix25 - the three final builds (all 0.25 deg/s soft deadzone)
| file | use |
|---|---|
| `CURRENT_1_gyro-accel-fix25-normal.uf2` | controller, USB-C UP (= fix23-normal-0.25) |
| `CURRENT_1_gyro-accel-fix25-inverted.uf2` | controller, USB-C DOWN (= fix23-inverted-0.25) |
| `CURRENT_1_gyro-accel-fix25-handheld.uf2` | normal axes + **2.0x gyro gain** for handhelds (Xbox ROG Ally X) |
| `handheld-extra/...-handheld-1.5x.uf2`, `...-3x.uf2` | same, 1.5x / 3x gain if 2x is too little/much |

Gain is applied after the deadzone (so the deadzone stays 0.25 deg/s in real motion), per axis, gyro only, saturating at int16.
No low-pass filter in firmware (needs RAM for state; none known to be free). For extra smoothing use JoyShockMapper `GYRO_SMOOTH_THRESHOLD` / `GYRO_SMOOTH_TIME`.
Rebuild: `make_axis_variant.py in out "+1,-2,-0" <deadzone_lsb> <gain_quarters>` (8 = 2.0x).

## fix26 - handheld, aim sideways by ROLLING
| file | use |
|---|---|
| `CURRENT_1_gyro-accel-fix26-handheld-roll.uf2` | pitch (up/down) as before; **roll drives the horizontal (left/right) channel**; 2.0x gain, 0.25 deg/s soft deadzone. Report `(+Gy, -Gx, +Gz)`. Try first. |
| `CURRENT_1_gyro-accel-fix26-handheld-roll-alt.uf2` | same but roll direction reversed (`(+Gy, +Gx, -Gz)`); use if rolling right moves the cursor left. |

Soft deadzone, per gyro axis, applied in the firmware before the report is sent: `|v| <= T` -> 0, larger motion is reduced by T so there is no jump at the edge. Accelerometer is untouched. Rebuild: `make_axis_variant.py in out "+1,-2,-0" <T in LSB, 16 LSB = 1 dps>`.

Notes
* fix16 sent `gyro=(-Gz,-Gx,+Gz)`, `accel=(+Az,-Ax,+Az)`: the sensor's Y axis was never sent and Z was sent twice.
  That is invisible while only yaw/pitch are used, but a re-orientation needs all three axes, so fix17 sends all three
  (a proper rotation) for both gyro and accel.
* Yaw (left/right) is unchanged from fix16; only pitch/roll are mixed.
* Rebuild: `python3 ../tools/make_axis_variant.py <fix16.uf2> <out.uf2> "+1,-2,-0"` (term = sign + sensor axis for report slots X,Y,Z).
* JoyShockMapper test: set `GYRO_SPACE = LOCAL` (X slot = vertical, Y slot = horizontal; the Z slot is ignored there).

## 1000 Hz
Report thread already sleeps 33 ticks of 32768 Hz (~1.007 ms) between reports; fix19 makes the USB side explicit (bInterval=1).
Sensor ODR is a runtime setting: in the serial shell run `read_config sensor_gyro_odr`, then `write_config sensor_gyro_odr 1000`,
`write_config sensor_accel_odr 1000`, `reboot` (driver rounds up to the next LSM6DSV ODR, 1920 Hz).
