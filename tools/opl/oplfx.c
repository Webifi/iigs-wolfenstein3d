/* Headless OPL2 effect renderer.
 * Links Nuked-OPL3 (this directory, LGPL-2.1-or-later) and drives it as a YM3812:
 * waveform select on, OPL3 new-bit left clear, one register write per line.
 * OPL3_Generate emits one native chip sample (49716 Hz) as a stereo pair.
 * AdLib sound effects are mono, so only the left sample is written.
 *
 * Script (text):
 *   reset
 *   out PATH
 *   reg REG VALUE
 *   gen COUNT
 */
#include "opl3.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    FILE *in, *out = NULL;
    opl3_chip chip;
    char line[640];
    if (argc != 2) {
        fprintf(stderr, "usage: oplfx SCRIPT\n");
        return 2;
    }
    in = fopen(argv[1], "r");
    if (!in) {
        perror(argv[1]);
        return 1;
    }
    OPL3_Reset(&chip, 49716);
    while (fgets(line, sizeof line, in)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r')
            continue;
        if (!strncmp(line, "reset", 5)) {
            OPL3_Reset(&chip, 49716);
        } else if (!strncmp(line, "out ", 4)) {
            char path[512];
            if (sscanf(line + 4, "%511s", path) != 1)
                return 1;
            if (out)
                fclose(out);
            out = fopen(path, "wb");
            if (!out) {
                perror(path);
                return 1;
            }
        } else if (!strncmp(line, "reg ", 4)) {
            unsigned reg, val;
            if (sscanf(line + 4, "%i %i", &reg, &val) != 2)
                return 1;
            OPL3_WriteReg(&chip, (uint16_t)reg, (uint8_t)val);
        } else if (!strncmp(line, "gen ", 4)) {
            unsigned n, i;
            if (!out)
                return 1;
            if (sscanf(line + 4, "%u", &n) != 1)
                return 1;
            for (i = 0; i < n; i++) {
                int16_t st[2];
                int16_t mono;
                OPL3_Generate(&chip, st);
                mono = st[0];
                if (fwrite(&mono, 2, 1, out) != 1)
                    return 1;
            }
        } else {
            fprintf(stderr, "bad line: %s", line);
            return 1;
        }
    }
    if (out)
        fclose(out);
    fclose(in);
    return 0;
}
