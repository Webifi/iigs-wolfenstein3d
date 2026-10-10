"""Small 65816 assembler. Tracks M/X so immediate widths match the CPU."""

class AsmError(Exception):
    pass


class Asm:
    def __init__(self, org, bank=0):
        self.org = org
        self.here = org
        self.bank = bank
        self.buf = bytearray()
        self.labels = {}
        self.fixups = []  # (buf_index, kind, label, pc_after_or_None)
        self.lines = []   # (addr, buf_lo, buf_hi, text)
        self.m = 1        # 1 = 8-bit accumulator
        self.x = 1        # 1 = 8-bit index
        self.comments = {}

    def label(self, name):
        if name in self.labels:
            raise AsmError("duplicate label %s" % name)
        self.labels[name] = self.here
        self.lines.append((self.here, len(self.buf), len(self.buf), "%s:" % name))

    def note(self, text):
        self.lines.append((self.here, len(self.buf), len(self.buf), "; " + text))

    def _op(self, text, *bs):
        start = self.here
        lo = len(self.buf)
        for b in bs:
            self.buf.append(b & 0xFF)
            self.here += 1
        self.lines.append((start, lo, len(self.buf), text))

    def _fix(self, kind, lab, pc_after, width):
        # placeholder bytes already emitted; point at the first of them
        self.fixups.append((len(self.buf) - width, kind, lab, pc_after))

    def emit_bytes(self, data, text="db"):
        self._op(text, *data)

    def emit_blob(self, data, text="blob"):
        """Append data without a per-byte listing line."""
        self.note("%s (%d bytes)" % (text, len(data)))
        self.buf.extend(data)
        self.here += len(data)

    def byte(self, *vals):
        self._op("fcb " + ",".join("$%02X" % (v & 0xFF) for v in vals), *vals)

    def word(self, val):
        self._op("fcw $%04X" % (val & 0xFFFF), val & 0xFF, (val >> 8) & 0xFF)

    def align(self, n, fill=0xEA):
        while self.here % n:
            self._op("align", fill)

    def skip_if_page_cross(self, nbytes):
        """Pad with NOP so the next nbytes stay on one page."""
        if nbytes > 0x100:
            raise AsmError("skip %d does not fit in a page" % nbytes)
        if ((self.here & 0xFF) + nbytes) > 0x100:
            while self.here & 0xFF:
                self.nop()

    def seek(self, addr):
        if addr < self.here:
            raise AsmError("seek backwards to $%04X from $%04X" % (addr, self.here))
        self.note("org $%04X" % addr)
        gap = addr - self.here
        if gap:
            self.buf.extend(b"\x00" * gap)
            self.here = addr

    def resolve(self):
        for idx, kind, lab, pc_after in self.fixups:
            if lab not in self.labels:
                raise AsmError("undefined label %s" % lab)
            target = self.labels[lab]
            if kind == "rel8":
                rel = target - pc_after
                if not -128 <= rel <= 127:
                    raise AsmError("rel8 out of range %s -> %d" % (lab, rel))
                self.buf[idx] = rel & 0xFF
            elif kind == "rel16":
                rel = target - pc_after
                if not -32768 <= rel <= 32767:
                    raise AsmError("rel16 out of range %s" % lab)
                self.buf[idx] = rel & 0xFF
                self.buf[idx + 1] = (rel >> 8) & 0xFF
            elif kind == "abs":
                self.buf[idx] = target & 0xFF
                self.buf[idx + 1] = (target >> 8) & 0xFF
            elif kind == "dp":
                off = target - self.org if False else target
                # direct-page operand is the low byte of the address when DP=0,
                # or an explicit offset stored as the label's address low 8
                # only when the label is in $00-$FF. Callers pass ZP labels.
                if target > 0xFF:
                    raise AsmError("dp label out of zero page: %s=$%04X" % (lab, target))
                self.buf[idx] = target & 0xFF
            else:
                raise AsmError("bad fixup %s" % kind)
        return bytes(self.buf)

    def listing(self):
        self.resolve()
        out = []
        for addr, lo, hi, text in self.lines:
            bs = self.buf[lo:hi]
            hexb = " ".join("%02X" % b for b in bs)
            full = (self.bank << 16) | addr
            out.append("%06X: %-16s %s" % (full, hexb, text))
        return "\n".join(out) + "\n"

    # ----- immediates -----
    def _imm_a(self, v):
        if self.m:
            return (v & 0xFF,)
        return (v & 0xFF, (v >> 8) & 0xFF)

    def _imm_x(self, v):
        if self.x:
            return (v & 0xFF,)
        return (v & 0xFF, (v >> 8) & 0xFF)

    def rep(self, v):
        self._op("rep #$%02X" % v, 0xC2, v & 0xFF)
        if v & 0x20:
            self.m = 0
        if v & 0x10:
            self.x = 0

    def sep(self, v):
        self._op("sep #$%02X" % v, 0xE2, v & 0xFF)
        if v & 0x20:
            self.m = 1
        if v & 0x10:
            self.x = 1

    def lda_i(self, v):
        self._op("lda #%s" % _fmt(v, self.m), 0xA9, *self._imm_a(v))

    def adc_i(self, v):
        self._op("adc #%s" % _fmt(v, self.m), 0x69, *self._imm_a(v))

    def sbc_i(self, v):
        self._op("sbc #%s" % _fmt(v, self.m), 0xE9, *self._imm_a(v))

    def cmp_i(self, v):
        self._op("cmp #%s" % _fmt(v, self.m), 0xC9, *self._imm_a(v))

    def and_i(self, v):
        self._op("and #%s" % _fmt(v, self.m), 0x29, *self._imm_a(v))

    def ora_i(self, v):
        self._op("ora #%s" % _fmt(v, self.m), 0x09, *self._imm_a(v))

    def eor_i(self, v):
        self._op("eor #%s" % _fmt(v, self.m), 0x49, *self._imm_a(v))

    def ldx_i(self, v):
        self._op("ldx #%s" % _fmt(v, self.x), 0xA2, *self._imm_x(v))

    def ldy_i(self, v):
        self._op("ldy #%s" % _fmt(v, self.x), 0xA0, *self._imm_x(v))

    def cpx_i(self, v):
        self._op("cpx #%s" % _fmt(v, self.x), 0xE0, *self._imm_x(v))

    def cpy_i(self, v):
        self._op("cpy #%s" % _fmt(v, self.x), 0xC0, *self._imm_x(v))

    def pea(self, v):
        self._op("pea #$%04X" % (v & 0xFFFF), 0xF4, v & 0xFF, (v >> 8) & 0xFF)

    # ----- direct page (numeric offset, DP as the CPU has it) -----
    def lda_d(self, d):
        self._op("lda $%02X" % d, 0xA5, d & 0xFF)

    def sta_d(self, d):
        self._op("sta $%02X" % d, 0x85, d & 0xFF)

    def adc_d(self, d):
        self._op("adc $%02X" % d, 0x65, d & 0xFF)

    def sbc_d(self, d):
        self._op("sbc $%02X" % d, 0xE5, d & 0xFF)

    def cmp_d(self, d):
        self._op("cmp $%02X" % d, 0xC5, d & 0xFF)

    def and_d(self, d):
        self._op("and $%02X" % d, 0x25, d & 0xFF)

    def ora_d(self, d):
        self._op("ora $%02X" % d, 0x05, d & 0xFF)

    def stz_d(self, d):
        self._op("stz $%02X" % d, 0x64, d & 0xFF)

    def inc_d(self, d):
        self._op("inc $%02X" % d, 0xE6, d & 0xFF)

    def dec_d(self, d):
        self._op("dec $%02X" % d, 0xC6, d & 0xFF)

    def ldx_d(self, d):
        self._op("ldx $%02X" % d, 0xA6, d & 0xFF)

    def ldy_d(self, d):
        self._op("ldy $%02X" % d, 0xA4, d & 0xFF)

    def stx_d(self, d):
        self._op("stx $%02X" % d, 0x86, d & 0xFF)

    def sty_d(self, d):
        self._op("sty $%02X" % d, 0x84, d & 0xFF)

    def lda_dx(self, d):
        self._op("lda $%02X,x" % d, 0xB5, d & 0xFF)

    def sta_dx(self, d):
        self._op("sta $%02X,x" % d, 0x95, d & 0xFF)

    def lda_diy(self, d):
        self._op("lda ($%02X),y" % d, 0xB1, d & 0xFF)

    def sta_diy(self, d):
        self._op("sta ($%02X),y" % d, 0x91, d & 0xFF)

    def lda_di(self, d):
        self._op("lda ($%02X)" % d, 0xB2, d & 0xFF)

    def sta_di(self, d):
        self._op("sta ($%02X)" % d, 0x92, d & 0xFF)

    def lda_dly(self, d):
        self._op("lda [$%02X],y" % d, 0xB7, d & 0xFF)

    def sta_dly(self, d):
        self._op("sta [$%02X],y" % d, 0x97, d & 0xFF)

    def lda_dl(self, d):
        self._op("lda [$%02X]" % d, 0xA7, d & 0xFF)

    def sta_dl(self, d):
        self._op("sta [$%02X]" % d, 0x87, d & 0xFF)

    def pei(self, d):
        self._op("pei $%02X" % d, 0xD4, d & 0xFF)

    def asl_d(self, d):
        self._op("asl $%02X" % d, 0x06, d & 0xFF)

    def lsr_d(self, d):
        self._op("lsr $%02X" % d, 0x46, d & 0xFF)

    # ----- absolute / long -----
    def _abs(self, opcode, mnem, addr):
        if isinstance(addr, str):
            self._op("%s %s" % (mnem, addr), opcode, 0, 0)
            self._fix("abs", addr, None, 2)
        else:
            self._op("%s $%04X" % (mnem, addr & 0xFFFF), opcode, addr & 0xFF, (addr >> 8) & 0xFF)

    def lda_a(self, addr):
        self._abs(0xAD, "lda", addr)

    def sta_a(self, addr):
        self._abs(0x8D, "sta", addr)

    def adc_a(self, addr):
        self._abs(0x6D, "adc", addr)

    def cmp_a(self, addr):
        self._abs(0xCD, "cmp", addr)

    def inc_a(self, addr):
        self._abs(0xEE, "inc", addr)

    def dec_abs(self, addr):
        self._abs(0xCE, "dec", addr)

    def ora_a(self, addr):
        self._abs(0x0D, "ora", addr)

    def and_a(self, addr):
        self._abs(0x2D, "and", addr)

    def eor_a(self, addr):
        self._abs(0x4D, "eor", addr)

    def stz_a(self, addr):
        self._abs(0x9C, "stz", addr)

    def ldx_a(self, addr):
        self._abs(0xAE, "ldx", addr)

    def ldy_a(self, addr):
        self._abs(0xAC, "ldy", addr)

    def stx_a(self, addr):
        self._abs(0x8E, "stx", addr)

    def sty_a(self, addr):
        self._abs(0x8C, "sty", addr)

    def jmp(self, addr):
        self._abs(0x4C, "jmp", addr)

    def jsr(self, addr):
        self._abs(0x20, "jsr", addr)

    def _abx(self, opcode, mnem, addr):
        if isinstance(addr, str):
            self._op("%s %s,x" % (mnem, addr), opcode, 0, 0)
            self._fix("abs", addr, None, 2)
        else:
            self._op("%s $%04X,x" % (mnem, addr & 0xFFFF), opcode, addr & 0xFF, (addr >> 8) & 0xFF)

    def _aby(self, opcode, mnem, addr):
        if isinstance(addr, str):
            self._op("%s %s,y" % (mnem, addr), opcode, 0, 0)
            self._fix("abs", addr, None, 2)
        else:
            self._op("%s $%04X,y" % (mnem, addr & 0xFFFF), opcode, addr & 0xFF, (addr >> 8) & 0xFF)

    def lda_ax(self, addr):
        self._abx(0xBD, "lda", addr)

    def lda_ay(self, addr):
        self._aby(0xB9, "lda", addr)

    def sta_ax(self, addr):
        self._abx(0x9D, "sta", addr)

    def adc_ax(self, addr):
        self._abx(0x7D, "adc", addr)

    def sbc_ax(self, addr):
        self._abx(0xFD, "sbc", addr)

    def cmp_ax(self, addr):
        self._abx(0xDD, "cmp", addr)

    def ldy_ax(self, addr):
        self._abx(0xBC, "ldy", addr)

    def _al(self, opcode, mnem, addr):
        self._op("%s $%06X" % (mnem, addr & 0xFFFFFF),
                 opcode, addr & 0xFF, (addr >> 8) & 0xFF, (addr >> 16) & 0xFF)

    def lda_al(self, addr):
        self._al(0xAF, "lda", addr)

    def sta_al(self, addr):
        self._al(0x8F, "sta", addr)

    def adc_al(self, addr):
        self._al(0x6F, "adc", addr)

    def cmp_al(self, addr):
        self._al(0xCF, "cmp", addr)

    def sta_alx(self, addr):
        self._al(0x9F, "sta", addr)

    def lda_alx(self, addr):
        self._al(0xBF, "lda", addr)

    def jml(self, addr):
        self._al(0x5C, "jml", addr)

    def jsl(self, addr):
        self._al(0x22, "jsl", addr)

    def mvn(self, dst, src):
        """MVN. Bytes are destination bank, then source bank (WDC order)."""
        self._op("mvn #$%02X,#$%02X" % (dst, src), 0x54, dst & 0xFF, src & 0xFF)

    def mvp(self, dst, src):
        self._op("mvp #$%02X,#$%02X" % (dst, src), 0x44, dst & 0xFF, src & 0xFF)

    # ----- branches -----
    def _rel(self, opcode, mnem, lab):
        self._op("%s %s" % (mnem, lab), opcode, 0)
        self._fix("rel8", lab, self.here, 1)

    def bra(self, lab):
        self._rel(0x80, "bra", lab)

    def bne(self, lab):
        self._rel(0xD0, "bne", lab)

    def beq(self, lab):
        self._rel(0xF0, "beq", lab)

    def bcc(self, lab):
        self._rel(0x90, "bcc", lab)

    def bcs(self, lab):
        self._rel(0xB0, "bcs", lab)

    def bpl(self, lab):
        self._rel(0x10, "bpl", lab)

    def bmi(self, lab):
        self._rel(0x30, "bmi", lab)

    def brl(self, lab):
        self._op("brl %s" % lab, 0x82, 0, 0)
        self._fix("rel16", lab, self.here, 2)

    # ----- implied -----
    def nop(self):
        self._op("nop", 0xEA)

    def clc(self):
        self._op("clc", 0x18)

    def sec(self):
        self._op("sec", 0x38)

    def cld(self):
        self._op("cld", 0xD8)

    def sei(self):
        self._op("sei", 0x78)

    def cli(self):
        self._op("cli", 0x58)

    def clv(self):
        self._op("clv", 0xB8)

    def dex(self):
        self._op("dex", 0xCA)

    def dey(self):
        self._op("dey", 0x88)

    def inx(self):
        self._op("inx", 0xE8)

    def iny(self):
        self._op("iny", 0xC8)

    def tax(self):
        self._op("tax", 0xAA)

    def tay(self):
        self._op("tay", 0xA8)

    def txa(self):
        self._op("txa", 0x8A)

    def tya(self):
        self._op("tya", 0x98)

    def txs(self):
        self._op("txs", 0x9A)

    def tsx(self):
        self._op("tsx", 0xBA)

    def tcd(self):
        self._op("tcd", 0x5B)

    def tcs(self):
        self._op("tcs", 0x1B)

    def tdc(self):
        self._op("tdc", 0x7B)

    def tsc(self):
        self._op("tsc", 0x3B)

    def txy(self):
        self._op("txy", 0x9B)

    def tyx(self):
        self._op("tyx", 0xBB)

    def xba(self):
        self._op("xba", 0xEB)

    def xce(self):
        self._op("xce", 0xFB)

    def phd(self):
        self._op("phd", 0x0B)

    def pld(self):
        self._op("pld", 0x2B)

    def phk(self):
        self._op("phk", 0x4B)

    def plb(self):
        self._op("plb", 0xAB)

    def phb(self):
        self._op("phb", 0x8B)

    def pha(self):
        self._op("pha", 0x48)

    def pla(self):
        self._op("pla", 0x68)

    def phx(self):
        self._op("phx", 0xDA)

    def plx(self):
        self._op("plx", 0xFA)

    def phy(self):
        self._op("phy", 0x5A)

    def ply(self):
        self._op("ply", 0x7A)

    def php(self):
        self._op("php", 0x08)

    def plp(self):
        self._op("plp", 0x28)

    def rtl(self):
        self._op("rtl", 0x6B)

    def rts(self):
        self._op("rts", 0x60)

    def dec_acc(self):
        self._op("dec a", 0x3A)

    def inc_acc(self):
        self._op("inc a", 0x1A)

    def asl_a(self):
        self._op("asl a", 0x0A)

    def lsr_a(self):
        self._op("lsr a", 0x4A)

    def ror_a(self):
        self._op("ror a", 0x6A)

    def mark(self, tid, start):
        """8-bit marker write. Restores M/X. See STOCK_COSTS.md."""
        sm, sx = self.m, self.x
        self.php()
        self.sep(0x20)
        if start:
            self.lda_i(tid)
            self.sta_al(0x0003F2)
            self.lda_i(1)
        else:
            self.lda_i(2)
        self.sta_al(0x0003F0)
        self.plp()
        self.m, self.x = sm, sx


def _fmt(v, eight):
    if eight:
        return "#$%02X" % (v & 0xFF)
    return "#$%04X" % (v & 0xFFFF)
