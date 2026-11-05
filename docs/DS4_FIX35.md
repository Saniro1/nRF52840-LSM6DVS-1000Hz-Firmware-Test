# DS4 fix35: three experimental test builds

This Test repository imports the complete `jsm-calibration` branch of
[Saniro1/Smol-Slime-Pre-Soldered-Board-with-LSM6DSV-NSRF52840-JSM-Firmware](https://github.com/Saniro1/Smol-Slime-Pre-Soldered-Board-with-LSM6DSV-NSRF52840-JSM-Firmware),
through commit `ef47e4c8117a910a5bb1e8ccdf0d6f7b8497567b` (fix34).
The source repository has not been modified. Historical files remain available.

## Use the matching release

Files are in `releases/ds4-fix35/`. SHA-256 hashes and build parameters are in
`manifest.json`. These are **experimental binary patches, not hardware-validated releases**.
Keep your currently working UF2 and a copy of your settings before testing.
Do not flash the unrelated Arduino `firmware/` sketch or generated web-demo images
onto this board. Their pinout, application offset and bootloader assumptions differ.

| File | Mounting | Gyro AND acceleration mapping |
|---|---|---|
| `fix35-ds4-normal.uf2` | normal / USB-C up | `(+Gy, -Gz, -Gx)` |
| `fix35-ds4-inverted.uf2` | inverted / USB-C down | `(-Gy, -Gz, +Gx)` |
| `fix35-ds4-handheld.uf2` | latest flipped handheld aiming directions | `(+Gy, +Gx, -Gz)` |

All three use unity gain and a 0.25 deg/s soft gyro deadzone before DS4 unit conversion.
Handheld preserves fix34's vertical/horizontal aiming directions but reverses its
third channel for **both** sensors. The old `(+Y,+X,+Z)` mapping has determinant -1;
`(+Y,+X,-Z)` has determinant +1, preserving a right-handed frame. Verify the third
axis physically before using world/player-space aim. Mounting descriptions are
inherited from earlier user testing, not newly measured here.

## Findings and changes

* The actual firmware is a patched SlimeVR / Zephyr image, not the Arduino sketch.
  The earlier branch repaired swapped gyro/accel slots and numerous axis mappings.
  The embedded USB modifications' source/ELF are absent, so this is a guarded patch
  build from the exact known fix19 UF2, not a full firmware-source rebuild.
* The original DS4 cave bypassed timestamp code and left bytes 10–11 zero. Fix35
  reads the existing 32768 Hz uptime clock and converts to DS4's 16/3 microsecond
  ticks, wrapping at 16 bits. No persistent RAM is allocated for this.
* The input converter at `0x99b8` produces 16 gyro counts/deg/s. JoyShockLibrary's
  DS4 parser uses `2000/32767` deg/s/count. Fix35 corrects the 2.34% sensitivity loss
  using `32767/32000`, then saturates. Accelerometer values already use 8192/g.
* Negating -32768 used to wrap on storage, potentially reversing maximum motion.
  Both gyro and acceleration now saturate after mapping. All three distinct axes
  are reported; gravity is retained, with no invented resting acceleration offset.
* Clear all 64 report bytes, center all sticks at 128, set no-touch flags and USB
  battery status at byte 30, and retain the original 64-byte USB submission.
* The endpoint already advertises 1 ms. The report loop slept 33 ticks (~1.007 ms)
  **plus processing**, which can miss host polls. It now retries every 16 ticks
  (~488 us), retaining the existing atomic in-flight guard and completion callback.
  This is a queue opportunity improvement, not proof of 1000 reports/s.
* `sensor_update_time_ms` was initialized to 6 ms and reset to 6 on returning to
  low-noise mode. Fix35 changes both to 1 ms, reducing FIFO batching latency.
  Sensor ODR and sleep modes remain runtime settings; configure them below.
* Previous fix32–34 hid the FIFO timestep warning. Fix35 keeps that diagnostic
  enabled. Repeated warnings, FIFO overruns or reconnects are failures to investigate,
  not messages to silence. Increased sensor/USB activity can increase CPU/power use.

The binary patches do **not** implement a new bias estimator or temperature model.
They retain the device's existing stored gyro bias and six-face accelerometer matrix.
A bigger deadzone hides motion and cannot replace calibration. Accelerometers cannot
observe absolute yaw; some long-term yaw drift remains possible with a six-axis IMU.

## Configure and calibrate the physical board

1. Save `read_config all` from the USB serial shell. Flash only the matching fix35
   UF2 using the previously working double-reset bootloader flow. Recovery is to
   flash your known working UF2; these patches preserve the base image's UF2 family,
   address range and boot code. They have not been recovery-tested here.
2. For wired high-rate operation, enter these shell commands, confirm each succeeds,
   then reboot. Existing stored settings can override firmware defaults:

   ```text
   write_config sensor_gyro_odr 1000
   write_config sensor_accel_odr 1000
   write_config sensor_use_low_power_2 0
   write_config use_imu_timeout 0
   write_config use_active_timeout 0
   write_config sensor_use_6_side_calibration 1
   reboot
   ```

   Reconnect and run `read_config all` again. A requested 1000 Hz is rounded up to
   1920 Hz by the LSM6DSV driver; 1000 USB reports/s and 1920 sensor samples/s are
   different rates. Saved ODR values alone do not prove actual throughput.
3. Warm up for 2–3 minutes. With six-side calibration enabled, run `calibrate` on
   a stable surface and keep completely still until **Finished calibration**.
   If it reports motion, timeout, or restoring previous calibration, it did not
   accept the new bias. Retry after resting. The upstream estimator checks
   acceleration stability, which cannot reliably reject slow constant rotation.
4. Run `6-side`. Rest the assembly on each of its six distinct faces (+/-X, +/-Y,
   +/-Z), following the serial prompts. Wait for each recorded side before moving.
   Support the assembly without covering, flexing or heating the IMU. Accept only
   the final success; confirm no restoration/error message. Reboot and verify.
   This calibrates the physical sensor, before the variant mapping. Recalibrate
   after hardware changes; switching mapping on the same board does not require
   erasing good calibration. Do not run `reset_data all` routinely.
5. Close JSM and other HID readers, then use the capture tool below. In JSM begin
   with Legacy/JoyShockLibrary and `GYRO_SPACE = LOCAL`, with prior gain/real-world
   calibration accounted for. Unity physical units now let sensitivity live in JSM.
   Full Sony feature-report, Bluetooth, console, SDL and DS4Windows compatibility
   are not implemented or claimed by this patch.

## Measure; do not infer 1000 Hz from bInterval

On the Windows/Linux PC physically connected to the board:

```sh
python -m pip install hidapi==0.14.0.post4
python tools/measure_ds4.py --list
python tools/measure_ds4.py --device 0 --seconds 30 --csv normal-rest.csv
python tools/measure_ds4.py --analyze-csv normal-rest.csv
```

Select the index matching this board, not another Sony controller. On Linux HID
permissions may need local configuration. Capture stationary first, then a separate
run rotating slowly about each physical axis. Repeat for each mounting and after
warming another 10 minutes. Preserve CSVs and serial logs for comparison.

The tool reads **real** 64-byte HID packets with no artificial sleep, using monotonic
host time. It reports arrival Hz, interval median/p95/p99/max, six-bit counter gaps,
timestamp changes, per-axis gyro mean/noise and gravity magnitude. Host scheduling
and buffering affect intervals; USBPcap/Wireshark or a USB analyzer is needed to
confirm bus-level 1 ms transactions. Aim for approximately 1000 reports/s sustained,
not merely a 1 ms descriptor. A 5 ms median/~200 Hz result is a remaining failure.

At rest gravity magnitude should be near 1 g across six faces (e.g. within 5% as an
initial screen), not zero. On movement verify all three channels and signs and that
90-degree rotations integrate consistently. A low output gyro mean is useful but
is measured **after** the soft deadzone; it cannot prove the raw bias is calibrated.
Unchanged motion values at rest cannot reveal sensor ODR. No device was attached to
this cloud machine, so physical calibration, effective sample freshness, drift,
USB rate, temperature behavior and runtime stability remain unverified.

## Reproduce and verify

```sh
bash tools/setup_firmware_env.sh
export PATH="/workspace/toolchain/gcc-arm-none-eabi-9-2019-q4-major/bin:$PATH"
python tools/build_fix35.py
/workspace/toolchain/venv/bin/python -m unittest discover -s tests -v
```

The strict UF2 reader rejects unknown magic/family/addresses, overlap, malformed
blocks and numbering. The builder also requires the exact base SHA-256, checks
patch preconditions and erased flash space, and emits a manifest. Tests execute
3018 actual ARM report paths with Unicorn, including int16 limits, all three
mappings, deadzone boundaries, timestamp rollover and preserved registers/stack.
Other tests restrict changed bytes to the declared locations, retain the timing
warning, and distinguish synthetic 200/1000 Hz capture fixtures. These host tests
do not run Zephyr, the sensor driver, DMA or a USB host controller.
