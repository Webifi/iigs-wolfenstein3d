"""Independent full-scale DOC attack and loop tables from measured samples."""
import math


def normalize(zone):
    """Keep each table's precision and carry its amplitude in register gain."""
    for source, table, gain in ((zone.float_tab, 'table', 'gain'),
                                (zone.float_lt, 'ltable', 'loop_gain')):
        peak = max(map(abs, source), default=0.) or 1.
        from audio_numeric import quantize
        encoded=quantize(source,peak)
        if encoded is None:encoded=bytes(max(1,min(255,128+round(v*127/peak))) for v in source)
        setattr(zone,table,encoded)
        setattr(zone, gain, -32*math.log2(peak))


def loop_attenuation(zone, tick, switch):
    """Change register gain on the same source tick as the table switch."""
    return getattr(zone, 'loop_gain', zone.gain)-zone.gain if tick >= switch else 0.
