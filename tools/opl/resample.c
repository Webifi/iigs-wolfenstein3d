/* Band-limit a Nuked-OPL3 left channel and resample it to the DOC rate.
   4th-order Butterworth, cutoff 0.45 times the destination rate, then linear
   interpolation. Input is 49716 Hz s16le. Output is f32le. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define SRC_RATE 49716.0

typedef struct {
    double b0, b1, b2, a1, a2, z1, z2;
} Biquad;

static Biquad biquad(double fs, double fc, double q)
{
    double w0 = 2.0 * acos(-1.0) * fc / fs;
    double cw = cos(w0), sw = sin(w0);
    double alpha = sw / (2.0 * q);
    double a0 = 1.0 + alpha;
    Biquad qf;
    qf.b0 = ((1.0 - cw) / 2.0) / a0;
    qf.b1 = (1.0 - cw) / a0;
    qf.b2 = qf.b0;
    qf.a1 = (-2.0 * cw) / a0;
    qf.a2 = (1.0 - alpha) / a0;
    qf.z1 = qf.z2 = 0.0;
    return qf;
}

static double step(Biquad *q, double s)
{
    double o = q->b0 * s + q->z1;
    q->z1 = q->b1 * s - q->a1 * o + q->z2;
    q->z2 = q->b2 * s - q->a2 * o;
    return o;
}

int main(int argc, char **argv)
{
    FILE *in, *out;
    double dst, fc;
    long n, i, m;
    int16_t *src;
    double *x;
    float *y;
    Biquad q0, q1;
    if (argc != 4) {
        fprintf(stderr, "usage: ym_resample IN.s16 OUT.f32 DST_RATE\n");
        return 2;
    }
    dst = atof(argv[3]);
    if (dst < 1000.0)
        return 2;
    in = fopen(argv[1], "rb");
    if (!in) {
        perror(argv[1]);
        return 1;
    }
    fseek(in, 0, SEEK_END);
    n = ftell(in) / 2;
    fseek(in, 0, SEEK_SET);
    src = malloc((size_t)n * sizeof *src);
    x = malloc((size_t)n * sizeof *x);
    if (!src || !x)
        return 1;
    if (n && fread(src, 2, (size_t)n, in) != (size_t)n)
        return 1;
    fclose(in);
    for (i = 0; i < n; i++)
        x[i] = src[i] / 32768.0;
    free(src);
    fc = 0.45 * dst;
    q0 = biquad(SRC_RATE, fc, 1.0 / (2.0 * cos(acos(-1.0) / 8.0)));
    q1 = biquad(SRC_RATE, fc, 1.0 / (2.0 * cos(3.0 * acos(-1.0) / 8.0)));
    for (i = 0; i < n; i++)
        x[i] = step(&q0, x[i]);
    for (i = 0; i < n; i++)
        x[i] = step(&q1, x[i]);
    m = (long)llround((double)n * dst / SRC_RATE);
    if (m < 1)
        m = 1;
    y = malloc((size_t)m * sizeof *y);
    if (!y)
        return 1;
    for (i = 0; i < m; i++) {
        double p = (double)i * SRC_RATE / dst;
        long j = (long)p;
        double f, s;
        if (j >= n - 1)
            s = x[n - 1];
        else {
            f = p - (double)j;
            s = x[j] * (1.0 - f) + x[j + 1] * f;
        }
        y[i] = (float)s;
    }
    free(x);
    out = fopen(argv[2], "wb");
    if (!out) {
        perror(argv[2]);
        return 1;
    }
    if (fwrite(y, 4, (size_t)m, out) != (size_t)m)
        return 1;
    fclose(out);
    free(y);
    return 0;
}
