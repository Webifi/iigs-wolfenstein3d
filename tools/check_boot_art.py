"""Check linear reduction, real error diffusion, determinism and loader contracts."""
import hashlib
import json
import struct
import time
from pathlib import Path
import numpy as np
import make_boot_picture as b
from shared_gray import picture

ROOT = Path(__file__).resolve().parents[1]

def check():
    # Averaging encoded RGB would yield .214 linear instead of .5 here.
    pixels = np.array([[[0, 0, 0], [255, 255, 255]]], dtype=np.uint8)
    assert np.allclose(b.shrink_linear(2, 1, 3, pixels.reshape(1, 6), 1, 1), .5)
    ramp = np.broadcast_to(np.linspace(.18, .58, b.WIDTH, dtype=np.float32)[None, :, None],
                           (b.ART_ROWS, b.WIDTH, 3)).copy()
    words = np.tile(np.arange(16)*0x111, (b.PALETTES, 1))
    result = b.diffuse(ramp, words, np.zeros(b.ART_ROWS, dtype=int))[:b.ART_ROWS]/15
    nearest = np.round(ramp[..., 0]*15)/15
    def block_error(values):
        residual = (values-ramp[..., 0])[:184]
        return float(np.square(residual.reshape(23, 8, 40, 8).mean(axis=(1, 3))).mean())
    assert block_error(result) < block_error(nearest)/3, 'diffusion did not preserve the smooth gradient'
    report = dict(gradient_diffused_error=block_error(result), gradient_nearest_error=block_error(nearest), pictures={})
    for key in ('wolf3d', 'shareware'):
        source = b.source_path(ROOT, key)
        began = time.perf_counter()
        raw = b.picture_record(b.read_png(source))
        seconds = time.perf_counter()-began
        assert raw == b.picture_record(b.read_png(source)), 'conversion is not deterministic'
        assert len(raw) == b.RECORD_BYTES
        assert not any(raw[b.ART_ROWS*b.WIDTH//2:b.SCB])
        assert not any(v >= b.PALETTES for v in raw[b.SCB:b.SCB+b.ART_ROWS])
        assert raw[b.SCB+b.ART_ROWS:b.SCB+b.HEIGHT] == bytes([b.PALETTES])*(b.HEIGHT-b.ART_ROWS)
        pals = np.frombuffer(raw[b.PAL:], dtype='<u2').reshape(16, 16)
        assert np.all(pals <= 0xfff) and not pals[:, 0].any()
        expected = [b.gscolor.word12(c) for c in b.gscolor.STRIP_COLORS]
        assert list(pals[15, :len(expected)]) == expected
        aligned = picture(raw, boot=True)
        # Slot alignment must preserve every displayed color, including the strip.
        for y in range(b.HEIGHT):
            p = raw[b.SCB+y]
            after = struct.unpack_from('<16H', aligned, b.PAL+p*32)
            for a, z in zip(raw[y*160:(y+1)*160], aligned[y*160:(y+1)*160]):
                assert pals[p, a >> 4] == after[z >> 4] and pals[p, a & 15] == after[z & 15]
        report['pictures'][key] = dict(seconds=round(seconds, 3), sha256=hashlib.sha256(raw).hexdigest(),
                                      source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    check()
