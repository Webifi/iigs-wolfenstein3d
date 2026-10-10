"""A small native-mode 65816 interpreter for differential tests of single routines.

Check tools run a routine of the built game on prepared memory and compare it with
the source model, in seconds and with exact nominal cycle counts (tools/check_sight_cast.py).

Memory is one flat 16 MB array. Cycle counts are nominal: the documented 65816 cycles
with the extra cycle of 16-bit registers, indexed absolute accesses always paying the
page-crossing cycle and branches taking 2 or 3. Native mode only, binary arithmetic,
no interrupts, no I/O. On the demo scenes it predicted a 1,406-cycle saving that the
demo timing then measured as 0.49 ms.
"""
import memmap
import struct

M8 = 0xff
M16 = 0xffff


class Trap(Exception):
    pass


# opcode -> (mnemonic, mode)
OPS = {}


def _alu(base, name):
    modes = {0x01: 'dpindx', 0x03: 'sr', 0x05: 'dp', 0x07: 'dpindl', 0x09: 'imm', 0x0d: 'abs', 0x0f: 'long',
             0x11: 'dpindy', 0x12: 'dpind', 0x13: 'sriy', 0x15: 'dpx', 0x17: 'dpindly', 0x19: 'absy', 0x1d: 'absx', 0x1f: 'longx'}
    for off, mode in modes.items():
        if name == 'sta' and mode == 'imm':
            continue
        OPS[base + off] = (name, mode)


for _b, _n in ((0x00, 'ora'), (0x20, 'and'), (0x40, 'eor'), (0x60, 'adc'), (0x80, 'sta'), (0xa0, 'lda'), (0xc0, 'cmp'), (0xe0, 'sbc')):
    _alu(_b, _n)
for _op, _n, _m in ((0x06, 'asl', 'dp'), (0x0a, 'asl', 'acc'), (0x0e, 'asl', 'abs'), (0x16, 'asl', 'dpx'), (0x1e, 'asl', 'absx'),
                    (0x26, 'rol', 'dp'), (0x2a, 'rol', 'acc'), (0x2e, 'rol', 'abs'), (0x36, 'rol', 'dpx'), (0x3e, 'rol', 'absx'),
                    (0x46, 'lsr', 'dp'), (0x4a, 'lsr', 'acc'), (0x4e, 'lsr', 'abs'), (0x56, 'lsr', 'dpx'), (0x5e, 'lsr', 'absx'),
                    (0x66, 'ror', 'dp'), (0x6a, 'ror', 'acc'), (0x6e, 'ror', 'abs'), (0x76, 'ror', 'dpx'), (0x7e, 'ror', 'absx'),
                    (0xe6, 'inc', 'dp'), (0x1a, 'inc', 'acc'), (0xee, 'inc', 'abs'), (0xf6, 'inc', 'dpx'), (0xfe, 'inc', 'absx'),
                    (0xc6, 'dec', 'dp'), (0x3a, 'dec', 'acc'), (0xce, 'dec', 'abs'), (0xd6, 'dec', 'dpx'), (0xde, 'dec', 'absx'),
                    (0x24, 'bit', 'dp'), (0x2c, 'bit', 'abs'), (0x34, 'bit', 'dpx'), (0x3c, 'bit', 'absx'), (0x89, 'bit', 'imm'),
                    (0xa2, 'ldx', 'imm'), (0xa6, 'ldx', 'dp'), (0xae, 'ldx', 'abs'), (0xb6, 'ldx', 'dpy'), (0xbe, 'ldx', 'absy'),
                    (0xa0, 'ldy', 'imm'), (0xa4, 'ldy', 'dp'), (0xac, 'ldy', 'abs'), (0xb4, 'ldy', 'dpx'), (0xbc, 'ldy', 'absx'),
                    (0x86, 'stx', 'dp'), (0x8e, 'stx', 'abs'), (0x96, 'stx', 'dpy'),
                    (0x84, 'sty', 'dp'), (0x8c, 'sty', 'abs'), (0x94, 'sty', 'dpx'),
                    (0x64, 'stz', 'dp'), (0x74, 'stz', 'dpx'), (0x9c, 'stz', 'abs'), (0x9e, 'stz', 'absx'),
                    (0xe0, 'cpx', 'imm'), (0xe4, 'cpx', 'dp'), (0xec, 'cpx', 'abs'),
                    (0xc0, 'cpy', 'imm'), (0xc4, 'cpy', 'dp'), (0xcc, 'cpy', 'abs'),
                    (0x10, 'bpl', 'rel'), (0x30, 'bmi', 'rel'), (0x50, 'bvc', 'rel'), (0x70, 'bvs', 'rel'),
                    (0x90, 'bcc', 'rel'), (0xb0, 'bcs', 'rel'), (0xd0, 'bne', 'rel'), (0xf0, 'beq', 'rel'), (0x80, 'bra', 'rel'),
                    (0x82, 'brl', 'rel16'),
                    (0xaa, 'tax', 'imp'), (0xa8, 'tay', 'imp'), (0x8a, 'txa', 'imp'), (0x98, 'tya', 'imp'), (0xba, 'tsx', 'imp'),
                    (0x9a, 'txs', 'imp'), (0x9b, 'txy', 'imp'), (0xbb, 'tyx', 'imp'), (0x5b, 'tcd', 'imp'), (0x7b, 'tdc', 'imp'),
                    (0x1b, 'tcs', 'imp'), (0x3b, 'tsc', 'imp'), (0xeb, 'xba', 'imp'),
                    (0x18, 'clc', 'imp'), (0x38, 'sec', 'imp'), (0x58, 'cli', 'imp'), (0x78, 'sei', 'imp'), (0xb8, 'clv', 'imp'),
                    (0xd8, 'cld', 'imp'), (0xf8, 'sed', 'imp'), (0xc2, 'rep', 'imm8'), (0xe2, 'sep', 'imm8'),
                    (0x48, 'pha', 'imp'), (0x68, 'pla', 'imp'), (0xda, 'phx', 'imp'), (0xfa, 'plx', 'imp'), (0x5a, 'phy', 'imp'),
                    (0x7a, 'ply', 'imp'), (0x08, 'php', 'imp'), (0x28, 'plp', 'imp'), (0x0b, 'phd', 'imp'), (0x2b, 'pld', 'imp'),
                    (0x8b, 'phb', 'imp'), (0xab, 'plb', 'imp'), (0x4b, 'phk', 'imp'), (0xf4, 'pea', 'imm16'), (0xd4, 'pei', 'dp'),
                    (0x4c, 'jmp', 'abs'), (0x6c, 'jmp', 'absind'), (0x7c, 'jmp', 'absindx'), (0x5c, 'jmp', 'long'),
                    (0x20, 'jsr', 'abs'), (0xfc, 'jsr', 'absindx'), (0x22, 'jsl', 'long'),
                    (0x54, 'mvn', 'block'), (0x60, 'rts', 'imp'), (0x6b, 'rtl', 'imp'), (0xea, 'nop', 'imp'),
                    (0xe8, 'inx', 'imp'), (0xc8, 'iny', 'imp'), (0xca, 'dex', 'imp'), (0x88, 'dey', 'imp'),
                    (0x04, 'tsb', 'dp'), (0x0c, 'tsb', 'abs'), (0x14, 'trb', 'dp'), (0x1c, 'trb', 'abs'),
                    (0x00, 'brk', 'imm8'), (0xdb, 'stp', 'imp')):
    OPS[_op] = (_n, _m)

_BASE = {'imm': 2, 'dp': 3, 'dpx': 4, 'dpy': 4, 'abs': 4, 'absx': 5, 'absy': 5, 'long': 5, 'longx': 5, 'dpind': 5, 'dpindx': 6,
         'dpindy': 6, 'dpindl': 6, 'dpindly': 6, 'sr': 4, 'sriy': 7}
_RMW = {'dp': 5, 'dpx': 6, 'abs': 6, 'absx': 7}
_IDXOPS = ('ldx', 'ldy', 'stx', 'sty', 'cpx', 'cpy')
_ALU = ('ora', 'and', 'eor', 'adc', 'sta', 'lda', 'cmp', 'sbc', 'bit', 'stz')


class Emu:
    def __init__(self):
        self.m = bytearray(1 << 24)
        self.a = 0
        self.x = self.y = 0
        self.s = 0x1fff
        self.d = 0
        self.db = 0
        self.pb = 0
        self.pc = 0
        self.n = self.v = self.z = self.c = 0
        self.mf = 0      # 1 = 8-bit accumulator
        self.xf = 0      # 1 = 8-bit index
        self.cycles = 0
        self.count = 0
        self.hist = None  # dict pc -> count when profiling

    # ---- memory
    def rd8(self, ea):
        return self.m[ea & 0xffffff]

    def rd16(self, ea):
        return self.m[ea & 0xffffff] | (self.m[(ea + 1) & 0xffffff] << 8)

    def wr8(self, ea, v):
        self.m[ea & 0xffffff] = v & 0xff

    def wr16(self, ea, v):
        self.m[ea & 0xffffff] = v & 0xff
        self.m[(ea + 1) & 0xffffff] = (v >> 8) & 0xff

    def load(self, addr, data):
        self.m[addr:addr + len(data)] = data

    # ---- stack
    def push8(self, v):
        self.m[self.s] = v & 0xff
        self.s = (self.s - 1) & 0xffff

    def push16(self, v):
        self.push8(v >> 8)
        self.push8(v)

    def pop8(self):
        self.s = (self.s + 1) & 0xffff
        return self.m[self.s]

    def pop16(self):
        lo = self.pop8()
        return lo | (self.pop8() << 8)

    # ---- flags
    def getp(self):
        return (self.n << 7) | (self.v << 6) | (self.mf << 5) | (self.xf << 4) | (self.z << 1) | self.c

    def setp(self, p):
        self.n = (p >> 7) & 1
        self.v = (p >> 6) & 1
        self.mf = (p >> 5) & 1
        self.xf = (p >> 4) & 1
        self.z = (p >> 1) & 1
        self.c = p & 1
        if self.xf:
            self.x &= 0xff
            self.y &= 0xff

    def nz(self, v, wide):
        if wide:
            self.n = (v >> 15) & 1
            self.z = int((v & 0xffff) == 0)
        else:
            self.n = (v >> 7) & 1
            self.z = int((v & 0xff) == 0)

    # ---- fetch
    def f8(self):
        v = self.m[(self.pb << 16) | self.pc]
        self.pc = (self.pc + 1) & 0xffff
        return v

    def f16(self):
        lo = self.f8()
        return lo | (self.f8() << 8)

    def f24(self):
        lo = self.f16()
        return lo | (self.f8() << 16)

    # ---- effective address
    def ea(self, mode):
        if mode == 'dp':
            return (self.d + self.f8()) & 0xffff
        if mode == 'dpx':
            return (self.d + self.f8() + self.x) & 0xffff
        if mode == 'dpy':
            return (self.d + self.f8() + self.y) & 0xffff
        if mode == 'abs':
            return (self.db << 16) | self.f16()
        if mode == 'absx':
            return ((self.db << 16) + self.f16() + self.x) & 0xffffff
        if mode == 'absy':
            return ((self.db << 16) + self.f16() + self.y) & 0xffffff
        if mode == 'long':
            return self.f24()
        if mode == 'longx':
            return (self.f24() + self.x) & 0xffffff
        if mode == 'dpind':
            p = (self.d + self.f8()) & 0xffff
            return (self.db << 16) | self.rd16(p)
        if mode == 'dpindx':
            p = (self.d + self.f8() + self.x) & 0xffff
            return (self.db << 16) | self.rd16(p)
        if mode == 'dpindy':
            p = (self.d + self.f8()) & 0xffff
            return ((self.db << 16) + self.rd16(p) + self.y) & 0xffffff
        if mode == 'dpindl':
            p = (self.d + self.f8()) & 0xffff
            return self.rd16(p) | (self.rd8(p + 2) << 16)
        if mode == 'dpindly':
            p = (self.d + self.f8()) & 0xffff
            return ((self.rd16(p) | (self.rd8(p + 2) << 16)) + self.y) & 0xffffff
        if mode == 'sr':
            return (self.s + self.f8()) & 0xffff
        if mode == 'sriy':
            p = (self.s + self.f8()) & 0xffff
            return ((self.db << 16) + self.rd16(p) + self.y) & 0xffffff
        raise Trap('mode ' + mode)

    # ---- helpers
    def adc(self, v, wide):
        mask = M16 if wide else M8
        a = self.a & mask
        r = a + (v & mask) + self.c
        self.c = int(r > mask)
        sign = 0x8000 if wide else 0x80
        self.v = int(((a ^ r) & ((v & mask) ^ r) & sign) != 0)
        r &= mask
        self.setacc(r)
        self.nz(r, wide)

    def sbc(self, v, wide):
        self.adc((~v) & (M16 if wide else M8), wide)

    def setacc(self, r):
        if self.mf:
            self.a = (self.a & 0xff00) | (r & 0xff)
        else:
            self.a = r & 0xffff

    def cmp(self, reg, v, wide):
        mask = M16 if wide else M8
        r = (reg & mask) - (v & mask)
        self.c = int(r >= 0)
        self.nz(r & mask, wide)

    # ---- run
    def step(self):
        pc0 = (self.pb << 16) | self.pc
        op = self.f8()
        if op not in OPS:
            raise Trap('unknown opcode %02x at %06x' % (op, pc0))
        name, mode = OPS[op]
        self.count += 1
        c_before = self.cycles
        w = not self.mf     # wide accumulator
        xw = not self.xf    # wide index
        cyc = 0

        def base(mode_):
            return _BASE[mode_]
        # ---- ALU group
        if name in ('ora', 'and', 'eor', 'adc', 'sbc', 'cmp', 'lda'):
            if mode == 'imm':
                v = self.f16() if w else self.f8()
                cyc = 2
            else:
                ea = self.ea(mode)
                v = self.rd16(ea) if w else self.rd8(ea)
                cyc = base(mode)
            cyc += int(w)
            wide = w
            if name == 'lda':
                self.setacc(v)
                self.nz(v, wide)
            elif name == 'ora':
                r = (self.a | v) & (M16 if wide else M8)
                self.setacc(r)
                self.nz(r, wide)
            elif name == 'and':
                r = (self.a & v) & (M16 if wide else M8)
                self.setacc(r)
                self.nz(r, wide)
            elif name == 'eor':
                r = (self.a ^ v) & (M16 if wide else M8)
                self.setacc(r)
                self.nz(r, wide)
            elif name == 'adc':
                self.adc(v, wide)
            elif name == 'sbc':
                self.sbc(v, wide)
            elif name == 'cmp':
                self.cmp(self.a, v, wide)
        elif name == 'sta':
            ea = self.ea(mode)
            if w:
                self.wr16(ea, self.a)
            else:
                self.wr8(ea, self.a)
            cyc = base(mode) + int(w)
        elif name == 'stz':
            ea = self.ea(mode)
            if w:
                self.wr16(ea, 0)
            else:
                self.wr8(ea, 0)
            cyc = base(mode) + int(w)
        elif name == 'bit':
            if mode == 'imm':
                v = self.f16() if w else self.f8()
                cyc = 2
                self.z = int((self.a & v & (M16 if w else M8)) == 0)
            else:
                ea = self.ea(mode)
                v = self.rd16(ea) if w else self.rd8(ea)
                cyc = base(mode)
                self.z = int((self.a & v & (M16 if w else M8)) == 0)
                self.n = (v >> (15 if w else 7)) & 1
                self.v = (v >> (14 if w else 6)) & 1
            cyc += int(w)
        elif name in ('tsb', 'trb'):
            ea = self.ea(mode)
            v = self.rd16(ea) if w else self.rd8(ea)
            mask = M16 if w else M8
            self.z = int((self.a & v & mask) == 0)
            r = (v | self.a) & mask if name == 'tsb' else v & ~self.a & mask
            if w:
                self.wr16(ea, r)
            else:
                self.wr8(ea, r)
            cyc = (5 if mode == 'dp' else 6) + 2 * int(w)
        elif name in ('ldx', 'ldy', 'cpx', 'cpy'):
            if mode == 'imm':
                v = self.f16() if xw else self.f8()
                cyc = 2
            else:
                ea = self.ea(mode)
                v = self.rd16(ea) if xw else self.rd8(ea)
                cyc = base(mode)
            cyc += int(xw)
            if name == 'ldx':
                self.x = v
                self.nz(v, xw)
            elif name == 'ldy':
                self.y = v
                self.nz(v, xw)
            elif name == 'cpx':
                self.cmp(self.x, v, xw)
            else:
                self.cmp(self.y, v, xw)
        elif name in ('stx', 'sty'):
            ea = self.ea(mode)
            reg = self.x if name == 'stx' else self.y
            if xw:
                self.wr16(ea, reg)
            else:
                self.wr8(ea, reg)
            cyc = base(mode) + int(xw)
        elif name in ('asl', 'lsr', 'rol', 'ror', 'inc', 'dec'):
            wide = w
            mask = M16 if wide else M8
            top = 0x8000 if wide else 0x80
            if mode == 'acc':
                v = self.a & mask
                cyc = 2
            else:
                ea = self.ea(mode)
                v = self.rd16(ea) if wide else self.rd8(ea)
                cyc = _RMW[mode] + 2 * int(wide)
            if name == 'asl':
                self.c = int((v & top) != 0)
                r = (v << 1) & mask
            elif name == 'lsr':
                self.c = v & 1
                r = v >> 1
            elif name == 'rol':
                c = self.c
                self.c = int((v & top) != 0)
                r = ((v << 1) | c) & mask
            elif name == 'ror':
                c = self.c
                self.c = v & 1
                r = (v >> 1) | (top if c else 0)
            elif name == 'inc':
                r = (v + 1) & mask
            else:
                r = (v - 1) & mask
            self.nz(r, wide)
            if mode == 'acc':
                self.setacc(r)
            elif wide:
                self.wr16(ea, r)
            else:
                self.wr8(ea, r)
        elif mode == 'rel' or mode == 'rel16':
            if mode == 'rel':
                off = self.f8()
                off = off - 256 if off > 127 else off
            else:
                off = self.f16()
                off = off - 65536 if off > 32767 else off
            take = {'bpl': not self.n, 'bmi': self.n, 'bvc': not self.v, 'bvs': self.v, 'bcc': not self.c, 'bcs': self.c,
                    'bne': not self.z, 'beq': self.z, 'bra': True, 'brl': True}[name]
            cyc = 2
            if take:
                self.pc = (self.pc + off) & 0xffff
                cyc = 3 if name != 'brl' else 4
        elif name in ('tax', 'tay', 'txa', 'tya', 'tsx', 'txs', 'txy', 'tyx', 'tcd', 'tdc', 'tcs', 'tsc', 'xba'):
            cyc = 2
            if name == 'tax':
                self.x = self.a & (M16 if xw else M8)
                self.nz(self.x, xw)
            elif name == 'tay':
                self.y = self.a & (M16 if xw else M8)
                self.nz(self.y, xw)
            elif name == 'txa':
                v = self.x & (M16 if w else M8)
                self.setacc(v)
                self.nz(v, w)
            elif name == 'tya':
                v = self.y & (M16 if w else M8)
                self.setacc(v)
                self.nz(v, w)
            elif name == 'txy':
                self.y = self.x
                self.nz(self.y, xw)
            elif name == 'tyx':
                self.x = self.y
                self.nz(self.x, xw)
            elif name == 'tcd':
                self.d = self.a & 0xffff
                self.nz(self.d, True)
            elif name == 'tdc':
                self.a = self.d
                self.nz(self.a, True)
            elif name == 'tcs':
                self.s = self.a & 0xffff
            elif name == 'tsc':
                self.a = self.s
                self.nz(self.a, True)
            elif name == 'tsx':
                self.x = self.s & (M16 if xw else M8)
                self.nz(self.x, xw)
            elif name == 'txs':
                self.s = self.x
            else:  # xba
                self.a = ((self.a & 0xff) << 8) | ((self.a >> 8) & 0xff)
                self.nz(self.a & 0xff, False)
                cyc = 3
        elif name in ('clc', 'sec', 'cli', 'sei', 'clv', 'cld', 'sed', 'nop'):
            cyc = 2
            if name == 'clc':
                self.c = 0
            elif name == 'sec':
                self.c = 1
            elif name == 'clv':
                self.v = 0
        elif name in ('rep', 'sep'):
            v = self.f8()
            p = self.getp()
            p = (p & ~v) if name == 'rep' else (p | v)
            self.setp(p)
            cyc = 3
        elif name in ('inx', 'iny', 'dex', 'dey'):
            cyc = 2
            mask = M16 if xw else M8
            if name == 'inx':
                self.x = (self.x + 1) & mask
                self.nz(self.x, xw)
            elif name == 'iny':
                self.y = (self.y + 1) & mask
                self.nz(self.y, xw)
            elif name == 'dex':
                self.x = (self.x - 1) & mask
                self.nz(self.x, xw)
            else:
                self.y = (self.y - 1) & mask
                self.nz(self.y, xw)
        elif name == 'mvn':
            # The renderer uses native, 16-bit-index block moves. Execute one
            # byte per step so overlap, wrapping, traces and cycles stay exact.
            if not xw:
                raise Trap('8-bit-index MVN is not implemented')
            dest, source = self.f8(), self.f8()
            self.wr8((dest << 16) | self.y, self.rd8((source << 16) | self.x))
            self.db = dest
            self.x = (self.x + 1) & M16
            self.y = (self.y + 1) & M16
            self.a = (self.a - 1) & M16
            if self.a != M16:
                self.pc = (self.pc - 3) & M16
            cyc = 7
        elif name == 'pha':
            if w:
                self.push16(self.a)
            else:
                self.push8(self.a)
            cyc = 3 + int(w)
        elif name == 'pla':
            if w:
                self.a = self.pop16()
            else:
                self.a = (self.a & 0xff00) | self.pop8()
            self.nz(self.a, w)
            cyc = 4 + int(w)
        elif name in ('phx', 'phy'):
            reg = self.x if name == 'phx' else self.y
            if xw:
                self.push16(reg)
            else:
                self.push8(reg)
            cyc = 3 + int(xw)
        elif name in ('plx', 'ply'):
            v = self.pop16() if xw else self.pop8()
            if name == 'plx':
                self.x = v
            else:
                self.y = v
            self.nz(v, xw)
            cyc = 4 + int(xw)
        elif name == 'php':
            self.push8(self.getp())
            cyc = 3
        elif name == 'plp':
            self.setp(self.pop8())
            cyc = 4
        elif name == 'phd':
            self.push16(self.d)
            cyc = 4
        elif name == 'pld':
            self.d = self.pop16()
            self.nz(self.d, True)
            cyc = 5
        elif name == 'phb':
            self.push8(self.db)
            cyc = 3
        elif name == 'plb':
            self.db = self.pop8()
            self.nz(self.db, False)
            cyc = 4
        elif name == 'phk':
            self.push8(self.pb)
            cyc = 3
        elif name == 'pea':
            self.push16(self.f16())
            cyc = 5
        elif name == 'pei':
            p = (self.d + self.f8()) & 0xffff
            self.push16(self.rd16(p))
            cyc = 6
        elif name == 'jmp':
            if mode == 'abs':
                self.pc = self.f16()
                cyc = 3
            elif mode == 'long':
                v = self.f24()
                self.pc = v & 0xffff
                self.pb = v >> 16
                cyc = 4
            elif mode == 'absind':
                a = self.f16()
                self.pc = self.rd16(a)       # bank 0
                cyc = 5
            else:  # absindx
                a = (self.f16() + self.x) & 0xffff
                self.pc = self.rd16((self.pb << 16) | a)
                cyc = 6
        elif name == 'jsr':
            if mode == 'abs':
                t = self.f16()
                self.push16((self.pc - 1) & 0xffff)
                self.pc = t
                cyc = 6
            else:
                a = (self.f16() + self.x) & 0xffff
                self.push16((self.pc - 1) & 0xffff)
                self.pc = self.rd16((self.pb << 16) | a)
                cyc = 8
        elif name == 'jsl':
            t = self.f24()
            self.push8(self.pb)
            self.push16((self.pc - 1) & 0xffff)
            self.pc = t & 0xffff
            self.pb = t >> 16
            cyc = 8
        elif name == 'rts':
            self.pc = (self.pop16() + 1) & 0xffff
            cyc = 6
        elif name == 'rtl':
            self.pc = (self.pop16() + 1) & 0xffff
            self.pb = self.pop8()
            cyc = 6
        elif name == 'brk':
            raise Trap('brk at %06x' % pc0)
        elif name == 'stp':
            raise StopIteration
        else:
            raise Trap('unimplemented %s %s' % (name, mode))
        self.cycles += cyc
        if self.hist is not None:
            h = self.hist.get(pc0)
            if h is None:
                self.hist[pc0] = [1, cyc]
            else:
                h[0] += 1
                h[1] += cyc

    def call(self, bank, addr, long_return=False, limit=2_000_000, sentinel=memmap.CALL_SENTINEL):
        """Run a routine until it returns to a sentinel. long_return: JSL-style."""
        self.m[sentinel] = 0xdb
        if long_return:
            self.push8(sentinel >> 16)
            self.push16((sentinel & 0xffff) - 1)
        else:
            self.push16((sentinel & 0xffff) - 1)
        self.pb = bank
        self.pc = addr
        # a JSR return lands in the routine's own bank, so place the sentinel there too
        if not long_return:
            self.m[(bank << 16) | (sentinel & 0xffff)] = 0xdb
        steps = 0
        try:
            while steps < limit:
                self.step()
                steps += 1
        except StopIteration:
            return
        raise Trap('did not return in %d steps' % limit)
