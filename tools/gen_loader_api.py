"""Resolve the resident boot loader's platform routines for level I/O."""
from elf import read
from wolfdata import ROOT

_, symbols = read(ROOT / 'build/boot/loader.elf')
names = ('readBlock', 'readHeader2', 'waitDisk', 'drawStrip', 'drawCell',
         'drawCount', 'drawText', 'LOADINGTEXT', 'XOFS', 'copyBlock', 'b1Seg', 'screenOn', 'readError', 'spUnit', 'buildId')
names += ('PD_UNIT', 'PD_BUF', 'PD_BLOCK', 'DEST', 'SEGADDR', 'DISKNUM',
          'NDISKS', 'CELLS', 'CCOLOR', 'HDR', 'BOOTINFO', 'BUF',
          'BAR_FULL', 'stripPal', 'runtimeUI', 'b1Notify', 'b1Progress')
lines = ['BOOT_%s .equ 0x%x' % (name, symbols[name]) for name in names]
# Calypsi omits expression-valued equates from the ELF symbols.
import re
source = (ROOT / 'src/iigs/loader.s').read_text()
import memmap
lines.append('BOOT_HDR_BUILD .equ 0x%x' % memmap.HDR_BUILD)
(ROOT / 'build/gen/loader_api.inc').write_text('\n'.join(lines) + '\n')
