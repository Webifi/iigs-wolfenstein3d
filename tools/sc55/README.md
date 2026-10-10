# Complete-track Roland capture

The patch adds an output-only mixer tap to the jcmoyer Nuked-SC55 headless
renderer. Every MIDI event still reaches the emulated firmware. Voice allocation,
filters, envelopes, layering and controller timing continue throughout the complete
instrument track. Selected partials feed the existing reverb/chorus and output
mixer; other partials continue running but their final mixer contributions are
muted. The SC-55 ROM supplies the instrument behaviour.

This differs from deleting MIDI notes or rendering isolated probes. Each capture
must have the identical complete register-write and partial-allocation trace as
ordinary playback. The ordinary instrumented render must also match the configured
reference renderer byte-for-byte. `audio_track_sampling.py` enforces both checks.

## Build once

Obtain the open source renderer from https://github.com/jcmoyer/Nuked-SC55.
Use a C++23-capable Clang or GCC installation. The builder uses Python's standard
library and leaves the input source tree untouched:

```sh
python3 tools/build_track_renderer.py --source /path/to/Nuked-SC55 --out /path/to/track-renderer
```

Set `track_executable` in the recipe's renderer settings to the resulting
`nuked-sc55-track-render` executable (`.exe` on Windows). Keep `executable` pointing
to the ordinary renderer. Both use the same user-supplied ROM set and reset policy.
`track_executable_sha256` optionally pins the capture executable. Patch context
must match exactly; source changes require reviewing and updating the patch.
The builder itself is portable Python; only the macOS build has been tested here.

The patch is a modification of Nuked-SC55's GPL-2.0-or-later source. Retain upstream
copyright and license notices with any distributed source or renderer binary.
ROM files are not part of this patch or its build.

## Capture checks

`SC55_CAPTURE_TRACE` names an internal trace file.
`SC55_CAPTURE_ACTIVATIONS` identifies selected PCM activations by output frame
and voice slot. The Python sampler sets these variables after resolving actual
partial ownership from the complete performance. A trace records every note, its PCM partial activation,
and a hash of all timestamped register writes. Capture groups leave at least eight
seconds after each selected note's release before another selected onset. Crops
must start from silence and retain the complete audible tail.

Firmware MIDI processing is asynchronous. A last-note-on label cannot identify
simultaneous percussion voices reliably. The sampler learns PCM pitch, loop and
stop signatures from isolated onsets in the same complete drum performance, then
resolves paired onsets only when those signatures identify each activation
unambiguously. Unresolved close onsets, missing partials and late activations
remain in the performance but are ineligible for extraction. The selector chooses
another actual occurrence at the required pitch; an explicit unsafe occurrence
fails. A part with no eligible occurrence fails.
Ordinary playback and gated captures must still have identical complete firmware
traces, and ordinary playback must match the reference renderer byte-for-byte.

The sampler captures notes as actually played. When a comparison root differs,
it changes the captured WAV's declared rate; it does not synthesize a new pitch
probe or invent a held-note duration. The original complete WAV and trace remain
available for debugging. A finite sound may be stopped by real voice reuse in the
track; that behaviour is part of the recorded context.

Wet mixer quantization prevents exact additivity of independently selected stems.
The first snare control preserved the ordinary WAV and every register write exactly;
recombining the selected hit and its complement differed by -46.34 dB relative RMS
over the tested window (at most 8 signed 16-bit counts). That is an extraction check,
not a claim that a reduced DOC bank has passed listening review.
