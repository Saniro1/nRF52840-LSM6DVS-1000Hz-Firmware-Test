# Correction: interpreting the stationary calibration screenshots

The screenshot's distinctive labels and scope match FlexInput's calibration UI.
The exact installed app/version is unknown; this identification is based on the
public source at commit 0905b2fe04258a8965eeb04663d7a5c6609d30ec.

Source:
https://github.com/x-iso/FlexInput/blob/0905b2fe04258a8965eeb04663d7a5c6609d30ec/crates/ui/src/panels/calibration.rs

## Corrected interpretation

The displayed acceleration peak is max(abs(displayed Accel X), abs(displayed Accel Y))
over the visible history. Displayed samples have the app's stored offsets subtracted
and may also be transformed by an alignment matrix. The peak includes residual bias
and tilt; it is not standard deviation or peak-to-peak noise about a mean.
The scope auto-zooms from the largest active channel value with padding.

Earlier statements interpreting 0.0327 G -> 0.0278 G as measured noise reduction
were too strong. The user reports slight improvement, but those labels alone
cannot quantify random-noise improvement. A constant 0.0278 G offset and a signal
alternating between +/-0.0278 G have the same absolute peak and radically
different variance. Visible fluctuations remain evidence of varying output;
the graph does not identify their source.

## Calibration behavior in the matching source

Manual Start gathers 250 UI-frame samples, estimates the three gyro offsets and
two horizontal acceleration offsets, and estimates noise using running variance.
It rejects sufficiently distant outliers after initialization. It leaves vertical
acceleration unchanged, retaining gravity in the expected flat body frame.
The frame count progresses independently of an SDL-style stationary-noise gate.
Auto-calibration has separate flat/still checks. Installed versions may differ.

Keep fix38 settings unchanged for a comparison. With the board supported level and
untouched, use the existing Start control if calibration has not already been
performed, and let it finish. This is ordinary per-device calibration, not a reason
to erase firmware calibration or increase deadzones. A textured scope after a
successful bias calibration does not alone mean calibration failed. A larger offset
caused by tilt or axis-frame problems should not be blindly zeroed in another
orientation.

## Firmware acquisition review

At 0x5486 the sensor loop calls the HID converter per valid FIFO record. A separate
SlimeVR accumulation/average at 0x5492 is not used by that HID path. Substituting
the existing batch average would add delay and reduce sample freshness at the
retained 6 ms collection interval; it does not establish 1000 fresh samples/s.

No stronger firmware filter is released on the basis of these screenshots.
Fix38 remains an unverified hardware-bandwidth experiment, not proof that physical
noise or SDL calibration is solved. The remaining noise spectrum, variance,
acquisition faults, physical bias and actual sensor/USB rates are unresolved.
