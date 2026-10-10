/* The preview's per-oscillator loop. The float store matches array('f'). */
#include <stdint.h>
#include <stddef.h>

uint64_t audio_preview_part(const unsigned char *ram, float *out,
                           size_t first, size_t end, uint64_t phase,
                           unsigned fc, unsigned shift, unsigned size,
                           unsigned table, unsigned control, double gain,
                           int *halted)
{
    uint64_t period = (uint64_t)size << shift;
    *halted = 0;
    for (size_t i = first; i < end; ++i) {
        phase += fc;
        unsigned at = (phase >> shift) & (size - 1);
        unsigned byte = ram[table + at];
        if (!byte || (phase >= period && (control & 6))) {
            *halted = 1;
            return 0;
        }
        if (phase >= period) phase %= period;
        out[i] = (float)((double)out[i] + ((int)byte - 128) * gain);
    }
    return phase;
}
