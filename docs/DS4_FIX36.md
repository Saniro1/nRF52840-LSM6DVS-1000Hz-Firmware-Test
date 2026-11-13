# Fix36: SDL unit correction and conservative diagnostic builds

Status: experimental; no physical board was attached. This is a partial repair,
not a resolution of stationary noise, reconnections, or the 1000 Hz requirement.
Investigated checkout: ds4-fix35 at 6a6d0a0ebb5ad7a85840b7018352ff06c08a16f5.
All three mappings are retained, prioritizing inverted for the first physical test.

## Confirmed findings

The actual board images are binary patches of the SHA-guarded fix19 UF2. The
repository history includes the supplied ef47e4c import. No embedded USB source
or matching ELF was recovered. Arduino and web generators were not used.

SDL source inspected: libsdl-org/SDL commit
fff6448f523f01e705d771a9f0ae782982b71482,
src/joystick/hidapi/SDL_hidapi_ps4.c. This is a reproducible upstream reference;
the user's installed SDL version is unknown.
https://github.com/libsdl-org/SDL/blob/fff6448f523f01e705d771a9f0ae782982b71482/src/joystick/hidapi/SDL_hidapi_ps4.c

* SDL's nominal DS4 gyro scale is 1/16 degree/s per count, converted internally
  to radians/s. Acceleration is 1/8192 g/count, converted to m/s². Fix35's
  32767/32000 gain is therefore wrong for SDL's nominal path. Fix36 removes it.
  JoyShockLibrary's different nominal conversion cannot simultaneously be exact
  with SDL's default conversion. This is not an accelerometer noise explanation.
* SDL requests USB calibration feature 0x02, requires at least 35 response bytes,
  validates bias/scales, and falls back to zero bias/unit scale on failure.
  Sony USB identity selects sensors and enhanced reports; enabling sensors loads
  calibration. USB report 1 with >=64 bytes and byte31 bit2 clear is accepted.
  The parser uses motion offsets 13..24 and timestamp 10..11, in 16/3 us units.
  It does not transform the three motion axes in this path.
* Embedded HID descriptor at 0x33144 is:
  05010905a10185010600ff0901150026ff007508953f810285020902952f9102850509039529b102850909049510b102c0
  It declares input 1 (63 payload bytes), output 2 (47), feature 5 (41), feature 9
  (16). It does NOT declare DS4 USB calibration feature 2 or serial feature 0x12.
  SDL motion detection does not establish complete DS4 compatibility. Fix36
  retains this descriptor: advertising new features without verified control
  handlers would not implement them. No synthetic factory calibration is added.
* Clock veneer 0x2faf8 branches to 0x2acd8. The latter masks BASEPRI, reads timer
  state, adds an elapsed value to a 64-bit accumulator, restores BASEPRI, and
  returns r0:r1, preserving r4-r6. Existing report code converts this clock to
  milliseconds by multiplying by 1000 and shifting by 15, consistent with 32768
  ticks/s. This strongly supports the clock interpretation, without ELF symbols.
  Fix35's low-word-only timestamp calculation is sufficient modulo 65536:
  the omitted upper-word contribution is a multiple of 2^19. It is report-build
  time, NOT a recovered FIFO sample timestamp. Repeated sensor samples can have
  different report timestamps. Neither timestamp nor bInterval measures ODR.
* Report function prologue 0x9770 saves 40 bytes. The cave adds a 16-byte save
  around its clock call, preserving 8-byte stack alignment given ABI entry.
  r0/r1 sensor pointers, r2 counter pointer and LR survive the call. The cave
  restores r0=device pointer and r8=8 as required at 0x985c. No demonstrated ABI
  corruption was found. Caller-saved r3/r12 are allowed to change.
* Atomic guard is acquired at 0x977c..0x9798, before clearing/building the buffer;
  callback 0x9748 clears it with barriers. The report spans RAM
  0x200051b3..0x200051f2. Original memset starts five bytes later and clears 59
  bytes, so clearing 64 from the actual start does not extend its footprint.
  This guard protects report reuse, not the separate sensor arrays.
* Producer 0x99b8 writes gyro halfwords at 0x2000510c and accel at 0x20005106
  sequentially. No lock surrounds these writes or cave reads. A mixed sample is
  possible under preemption; actual scheduling/interleaving remains unproven.
  A reader-only interrupt mask cannot fix preemption of a partially completed
  producer. No speculative interrupt masking or RAM allocation was introduced.
* 0x13b24 converts collection milliseconds to an integer sample count using a
  runtime sample period, then calls a driver function. The 1 ms patch therefore
  changes more than USB latency: integer rounding and low-ODR states matter.
  The warning at 0x5034 compares expected versus collected counts. Driver FIFO
  overrun behavior, state transitions, priorities and actual ODR remain unresolved.

## What these builds change

Fix36 starts from fix19, retains fix35's packet clearing, timestamps, saturation,
status fields and proper-rotation mappings, removes the soft gyro deadzone and
JSL gain, and restores 6 ms collection and 33-tick USB retry. It is a diagnostic
baseline, deliberately not a high-rate release. A 1 ms endpoint remains; 33 ticks
plus work cannot guarantee one report per USB frame. Restoring timing is a risk
reduction and comparison point, not proof timing caused the reported symptoms.
Gravity and stored physical calibration remain intact.

## Reproduce

Run tools/setup_firmware_env.sh, then:

```sh
export PATH="/workspace/toolchain/gcc-arm-none-eabi-9-2019-q4-major/bin:$PATH"
python tools/build_fix36.py
/workspace/toolchain/venv/bin/python -m unittest discover -s tests -v
```

All three UF2 files and hashes are in releases/ds4-fix36. Re-running the builder
must reproduce the hashes. Existing fix35 artifacts remain unchanged.
Tests execute 3018 fix36 ARM report paths, all mappings and int16 limits, clock
wrap, clobbered caller-saved clock registers, call alignment, preserved registers,
stack and output boundaries. Fix35's 3018 vectors also still run. These tests stub
the clock; they do not run Zephyr, FIFO, USB, interrupts, flash or calibration.

## Physical diagnosis before calibration (inverted first)

1. Preserve your known recoverable UF2 and `read_config all` output. Use your
   established double-reset UF2 bootloader procedure. Test fix36 inverted first.
   If it fails to enumerate, return to the bootloader and restore that known UF2.
   Recovery has not been physically tested here. Do not flash Arduino/web output.
2. Keep existing settings unchanged for the first fix35/fix36 A/B comparison;
   save settings and serial output with every capture. Close other HID consumers.
   Run `python tools/measure_ds4.py --list`, then
   `python tools/measure_ds4.py --device INDEX --seconds 60 --csv inverted-rest.csv`.
   The tool now uses SDL nominal gyro units and reports each acceleration axis's
   mean, standard deviation and peak-to-peak, retaining gravity. Capture another
   run with slow rotation around each axis. Old fix35 data also includes its gain
   and deadzone; this updated decoder does not undo those transformations.
3. Simultaneously capture OS USB events: on Linux save `journalctl -kf` output;
   on Windows use USBPcap/Wireshark and USB device/event logs. Keep serial logs
   separately and note that opening serial may alter DTR behavior. Match event
   times with wall-clock start/end notes. HID arrival timestamps are monotonic.
   USB disconnect/reset/enumeration or a serial boot banner supports a real
   device/bus event. SDL removal alone with continued HID/bus traffic supports a
   host-side failure. Neither alone proves watchdog, power, cable or firmware cause.
   A HID read error is recorded and partial CSV preserved; it does not classify
   the cause. Timeouts and counter gaps likewise are evidence, not reset proof.
4. Do not tune calibration until continuous captures and USB logs are stable.
   Then warm up, retain successful existing physical calibration, or use serial
   `calibrate` and `6-side` following prompts. Accept only explicit success; motion,
   timeout or restoration messages mean failure. Do not erase all stored data.
   Check six resting faces for ~1 g magnitude, axis signs, per-axis noise and
   temperature changes. No threshold for SDL Controller Test's Noise Progress
   has been established; its application source/version was not supplied.
5. After stable baseline measurements, separately test collection cadence and
   USB retry changes, one at a time, with sustained bus and FIFO evidence. Target
   1000 completed USB reports/s over minutes, measuring gaps and disconnects.
   Host buffered arrival rate is not bus scheduling. Verify sample freshness
   separately. Repeat normal and handheld and check all aiming directions.

Outstanding: real stationary/rotation CSVs, correlated bus/serial/SDL evidence,
actual control-feature responses/descriptors from the host, exact SDL/application
versions, runtime FIFO and scheduling analysis, physical units/calibration tests,
and sustained 1000 Hz. These artifacts do not establish those results.
