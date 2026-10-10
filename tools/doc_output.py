"""Stock ROM01 analog output reconstruction, without a musical-level adjustment.

The board's filter follows its multiplexed DAC. Model the SR15/SC14 pole and
SR16/SR43/SC17/SC16 pair from ROM01 sound sheet 8. Coefficients also used by the
corrected MAME IIgs model; this integrates individual DAC holds before sampling.
Summing linear state contributions within each output frame avoids advancing
all filter modes for every oscillator slot.
"""
from array import array
import cmath
import math

POLES = (-303030.30303030304, complex(-25641.025641025644, 62620.223433255531))
GAINS = (.056621431913898006, complex(.47168928404305094, -.33014257581209661))


class Output:
    def __init__(self, clock, rate, end):
        self.clock, self.rate = clock, rate
        self.frames = end * rate // clock
        self.raw, self.real, self.pair_r, self.pair_i = [array('d', [0.]) * (self.frames + 2) for _ in range(4)]
        self.exponents = []
        for ticks in range(math.ceil(clock / rate) + 2):
            first = math.exp(POLES[0] * ticks / clock)
            pair = cmath.exp(POLES[1] * ticks / clock)
            self.exponents.append((first, pair.real, pair.imag))

    def add(self, product, start, end):
        while start < end:
            frame = start * self.rate // self.clock
            # A rounded-down output edge belongs to the following frame.
            boundary = (frame + 1) * self.clock // self.rate
            if boundary <= start:
                frame += 1
                boundary = (frame + 1) * self.clock // self.rate
            if frame >= self.frames:
                return
            stop = min(end, boundary)
            a = self.exponents[boundary - stop]
            b = self.exponents[boundary - start]
            self.raw[frame] += product * (stop - start)
            self.real[frame] += product * (a[0] - b[0])
            self.pair_r[frame] += product * (a[1] - b[1])
            self.pair_i[frame] += product * (a[2] - b[2])
            start = stop

    def finish(self, start, system_volume):
        first = GAINS[0] / POLES[0] * self.clock
        pair = 2 * GAINS[1] / POLES[1] * self.clock
        state0 = state_r = state_i = 0.
        previous = 0
        factor = 17. / (4 * 32768) * (system_volume / 15)
        result = self.raw
        for frame in range(self.frames):
            boundary = (frame + 1) * self.clock // self.rate
            ticks = boundary - previous
            previous = boundary
            a, b, c = self.exponents[ticks]
            next0 = state0 * a + self.real[frame]
            next_r = state_r * b - state_i * c + self.pair_r[frame]
            next_i = state_i * b + state_r * c + self.pair_i[frame]
            # For each mode w'=p*(w-input), integral(w) is integral(input)
            # plus (w_end-w_start)/p. The filter's DC transfer is unity.
            integral = result[frame] + first * (next0 - state0) + pair.real * (next_r - state_r) - pair.imag * (next_i - state_i)
            result[frame] = integral * factor / ticks
            state0, state_r, state_i = next0, next_r, next_i
        return result[start * self.rate // self.clock:self.frames]
