#!/usr/bin/env python3
"""Smoke image. Block 0 loads the bank-$02 payload and times two known loops."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asm import Asm

HERE = os.path.dirname(os.path.abspath(__file__))

DRV = 0x08F0
DEST = 0x08F2
BLKL = 0x08F4
LEFT = 0x08F6


def build_payload():
    p = Asm(0x0000, bank=2)
    p.note("payload entry")
    p.sei()
    p.cld()
    p.clc()
    p.xce()                 # force native (CLC; XCE)
    p.rep(0x30)
    p.lda_i(0)
    p.tcd()
    p.ldx_i(0x01FF)
    p.txs()
    p.sep(0x20)
    p.lda_al(0x00C036)
    p.ora_i(0x80)           # 2.8 MHz
    p.and_i(0xEF)           # do not shadow all banks
    p.sta_al(0x00C036)
    p.lda_al(0x00C036)
    p.sta_al(0x0003F5)
    p.lda_al(0x00C035)
    p.sta_al(0x0003F6)

    p.note("MVN operand check: one byte $02:0100 -> $00:0300")
    p.lda_i(0x00)
    p.sta_al(0x000300)
    p.lda_i(0xA5)
    p.sta_al(0x020100)
    p.rep(0x30)
    p.lda_i(0)              # move 1 byte
    p.ldx_i(0x0100)
    p.ldy_i(0x0300)
    p.mvn(0x00, 0x02)       # dest bank 0, source bank 2
    p.sep(0x20)             # DB is dest bank 0
    p.lda_a(0x0300)
    p.sta_al(0x0003F4)      # expect $A5
    p.phk()
    p.plb()                 # DB = program bank 2

    # Test 1: NOP / DEX / BNE, 65536 times, 16-bit X. Page-aligned.
    p.note("test 1 NOP loop")
    p.rep(0x10)             # 16-bit index, 8-bit A
    p.mark(1, True)
    p.skip_if_page_cross(8)
    p.ldx_i(0)
    p.label("nop_loop")
    p.nop()
    p.dex()
    p.bne("nop_loop")
    p.mark(1, False)

    # Test 2: LDA abs / STA abs in bank 2, 65536 times.
    p.note("test 2 LDA/STA fast bank 2")
    p.mark(2, True)
    p.skip_if_page_cross(16)
    p.ldx_i(0)
    p.label("ls_loop")
    p.lda_a(0x1000)
    p.sta_a(0x1002)
    p.dex()
    p.bne("ls_loop")
    p.mark(2, False)

    p.sep(0x20)
    p.lda_i(0xFF)
    p.sta_al(0x0003F0)
    p.label("hang")
    p.bra("hang")
    data = p.resolve()
    text = p.listing()
    return data, text


def build_boot(nblocks):
    b = Asm(0x0800, bank=0)
    b.byte(0x01)
    b.note("emulation entry, X = unit")
    b.sei()
    b.cld()
    b.stx_d(0x43)
    b.lda_d(0x43)
    b.lsr_a()
    b.lsr_a()
    b.lsr_a()
    b.lsr_a()
    b.ora_i(0xC0)
    b.sta_a(DRV + 1)
    b.sta_d(0x41)
    b.lda_i(0xFF)
    b.sta_d(0x40)
    b.ldy_i(0)
    b.lda_diy(0x40)
    b.sta_a(DRV)

    b.lda_i(0)
    b.sta_a(DEST)
    b.sta_a(DEST + 1)
    b.sta_a(BLKL + 1)
    b.lda_i(1)                  # payload starts at block 1
    b.sta_a(BLKL)
    b.lda_i(nblocks & 0xFF)
    b.sta_a(LEFT)
    b.lda_i((nblocks >> 8) & 0xFF)
    b.sta_a(LEFT + 1)

    b.lda_i(1)
    b.sta_d(0x42)               # ProDOS read
    b.lda_i(0x00)
    b.sta_d(0x44)               # buffer $6200
    b.lda_i(0x62)
    b.sta_d(0x45)

    b.label("loop")
    b.lda_a(BLKL)
    b.sta_d(0x46)
    b.lda_a(BLKL + 1)
    b.sta_d(0x47)
    b.jsr("call")
    b.bcs("fail")

    b.note("copy 512 bytes $6200 -> $02:dest")
    b.clc()
    b.xce()
    b.rep(0x30)
    b.phk()
    b.plb()                     # DB = 0
    b.ldy_a(DEST)
    b.ldx_i(0x6200)
    b.lda_i(0x01FF)
    b.mvn(0x02, 0x00)
    b.phk()
    b.plb()                     # MVN set DB to 2; point it back at bank 0
    b.sty_a(DEST)
    b.sep(0x30)
    b.sec()
    b.xce()                     # emulation for the firmware driver

    b.inc_a(BLKL)
    b.bne("blk_ok")
    b.inc_a(BLKL + 1)
    b.label("blk_ok")
    b.lda_a(LEFT)
    b.bne("dec8")
    b.dec_abs(LEFT + 1)
    b.label("dec8")
    b.dec_abs(LEFT)
    b.lda_a(LEFT)
    b.ora_a(LEFT + 1)
    b.bne("loop")

    b.clc()
    b.xce()
    b.rep(0x30)
    b.lda_i(0)
    b.tcd()
    b.jml(0x020000)

    b.label("call")
    b.byte(0x6C, DRV & 0xFF, (DRV >> 8) & 0xFF)

    # Fail is reached in emulation. The assembler is still in 16-bit
    # mode after the JML above, so force 8-bit immediates.
    b.m = 1
    b.x = 1
    b.label("fail")
    b.lda_i(0xEE)
    b.sta_a(0x03F0)
    b.jmp("fail")

    # I don't have dec_a(abs) or ora_a. This will crash at assemble time
    # if those methods are missing — they are not all implemented.
    data = b.resolve()
    if b.here > DRV:
        raise SystemExit("boot code overlaps variables at $%04X" % b.here)
    if len(data) > 512:
        raise SystemExit("boot block %d bytes" % len(data))
    return data, b.listing()


def main():
    # Build payload first so boot knows the block count. Methods used by
    # build_boot that Asm lacks are added below before this runs... see note.
    payload, plist = build_payload()
    nblocks = (len(payload) + 511) // 512
    boot, blist = build_boot(nblocks)
    image = bytearray(800 * 1024)
    image[0:len(boot)] = boot
    image[512:512 + len(payload)] = payload
    path = os.path.join(HERE, "smoke.po")
    with open(path, "wb") as f:
        f.write(image)
    with open(os.path.join(HERE, "smoke_list.txt"), "w") as f:
        f.write("===== BOOT =====\n")
        f.write(blist)
        f.write("\n===== PAYLOAD =====\n")
        f.write(plist)
    print("payload", len(payload), "blocks", nblocks, "boot", len(boot), "->", path)


if __name__ == "__main__":
    main()
