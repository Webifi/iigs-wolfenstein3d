;;; Initial view and Fast walls selection. Valid saved choices always win.
;;; If either choice is unset, one startup probe supplies both defaults.
;;; ViewApply runs before the title song and returns twice the selected size
;;; for weaponViewIndex. ViewCollect retains the sentinel while the current
;;; size matches viewChosen; it updates only the in-memory settings image.
;;;
;;; The timing probe compares two loops in bank 2. Loop A uses 32 STA abs
;;; instructions with 8-bit A; loop B substitutes two NOPs per store. Each
;;; pass costs 133 nominal CPU cycles with a taken loop branch, and each
;;; batch contains 64 passes (8512 nominal cycles). I_GetTime is polled
;;; between batches; the long run amortizes the DOC access slowdown.
;;; A starts on a DOC tic boundary. B gets its own VT_TICS interval starting
;;; at the last timer reading from A, so A's overshoot cannot shorten B.
;;;
;;; The B count selects 3/4 view at roughly 7 MHz. At roughly 8 MHz and
;;; above, the A/B ratio measures write throughput relative to CPU speed:
;;; store-sensitive machines keep 3/4 view, balanced machines take full view.
;;; Only these measured counts choose the class, without identifying the card.
;;; A stalled clock or wrapped batch count falls back to the 2/3 view.
;;; The probe enables CPU IRQs so TWGS SLOW IRQ at CARD does not hold it at
;;; motherboard speed. It restores the caller's flags and never changes the
;;; card configuration. DBR=2 addresses the loops' scratch and clock.
#include "frontend.inc"
              .section viewtest, text, root, noreorder
              .public ViewCollect, ViewDefault
              .public viewChosen, viewTestA, viewTestB, viewTestKind, viewTestSize
              .extern I_GetTime, weaponViewIndex

VT_TICS       .equ 8                  ; nominal interval in 1/70-second DOC tics
VT_PASSES     .equ 64                 ; passes in one batch
VT_ACCEL      .equ 64                 ; margin for keyboard slowdown at 7 MHz; stock is 33-34
VT_FAST       .equ 96                 ; 8 MHz and above can select full view from the ratio
VT_TWOTHIRDS  .equ 1                  ; the sizes of S_VIEW
VT_THREEQUARTERS .equ 2
VT_FULL       .equ 3
VT_NONE       .equ 0                  ; classifications: invalid, stock, 3/4 accelerator, balanced
VT_STOCK      .equ 1
VT_STALL      .equ 2                  ; 7 MHz or store-sensitive: 3/4 view
VT_NATIVE     .equ 3

;;; Eight stores of loop A, from byte n of the scratch.
STORES        .macro n
              sta abs:.word0 (vtScratch + \n)
              sta abs:.word0 (vtScratch + \n + 1)
              sta abs:.word0 (vtScratch + \n + 2)
              sta abs:.word0 (vtScratch + \n + 3)
              sta abs:.word0 (vtScratch + \n + 4)
              sta abs:.word0 (vtScratch + \n + 5)
              sta abs:.word0 (vtScratch + \n + 6)
              sta abs:.word0 (vtScratch + \n + 7)
              .endm

;;; Sixteen NOPs match the nominal 32 cycles of eight STA abs stores.
IDLES         .macro
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              .endm

;;; Update S_VIEW, retaining S_VIEW_NOTSET if the auto-selected size is unchanged.
;;; Flags, X, Y and DBR are the caller's; A is not.
ViewCollect:  php
              rep #0x30
              phx
              lda long:weaponViewIndex
              lsr a
              tax                         ; X = the size now
              sep #0x20
              lda long:SETTINGS_IN + S_VIEW
              cmp #4
              bcc vcSize                  ; the settings name a size: keep it current
              rep #0x20
              txa
              cmp long:viewChosen         ; none yet: the size that the test chose stays "not set"
              sep #0x20
              beq vcDone
vcSize:       txa
              sta long:SETTINGS_IN + S_VIEW
vcDone:       rep #0x20
              plx
              plp
              rtl

;;; A = 1 (2/3), 2 (3/4) or 3 (full). Flags and DBR are the caller's; X and Y
;;; are not. Warm both loops before starting on the DOC tic edge.
ViewDefault:  php
              cli
              rep #0x30
              phb
              pea #0x0202
              plb
              plb
              stz abs:.word0 (viewTestA)
              stz abs:.word0 (viewTestB)
              lda ##VT_NONE
              sta abs:.word0 (viewTestKind)
              jsr abs:.word0 (vtStores)
              jsr abs:.word0 (vtIdles)
              jsl long:I_GetTime
              sta abs:.word0 (vtTic)
              ldy ##0                     ; 65536 reads at most: a clock that stands still ends it
vtEdge:       jsl long:I_GetTime
              cmp abs:.word0 (vtTic)
              bne vtEdgeA
              dey
              bne vtEdge
              jmp abs:.word0 (vtResult)
vtEdgeA:      sta abs:.word0 (vtTic)

vtBatchA:     jsr abs:.word0 (vtStores)
              inc abs:.word0 (viewTestA)
              bne vtTimeA
              jmp abs:.word0 (vtDead)
vtTimeA:      jsl long:I_GetTime
              sta abs:.word0 (vtNow)
              sec
              sbc abs:.word0 (vtTic)
              cmp ##VT_TICS
              bcs vtEndA
              jmp abs:.word0 (vtBatchA)
vtEndA:       lda abs:.word0 (vtNow)      ; B starts at the last timer reading from A
              sta abs:.word0 (vtTic)

vtBatchB:     jsr abs:.word0 (vtIdles)
              inc abs:.word0 (viewTestB)
              bne vtTimeB
              jmp abs:.word0 (vtDead)
vtTimeB:      jsl long:I_GetTime
              sec
              sbc abs:.word0 (vtTic)
              cmp ##VT_TICS
              bcs vtEndB
              jmp abs:.word0 (vtBatchB)

;;; B below VT_ACCEL selects stock; below VT_FAST selects 3/4 regardless
;;; of write bandwidth. Faster results compare A with B - floor(B/16).
;;; The 12 MHz TWGS loses about 1/10 of B to stores; 15/16 separates that
;;; from near-native write bandwidth while allowing timer quantization.
vtEndB:       lda abs:.word0 (viewTestB)
              cmp ##VT_ACCEL
              bcc vtStock
              cmp ##VT_FAST
              bcc vtStall
              lsr a
              lsr a
              lsr a
              lsr a
              sta abs:.word0 (vtLimit)
              lda abs:.word0 (viewTestB)
              sec
              sbc abs:.word0 (vtLimit)
              sta abs:.word0 (vtLimit)    ; B - floor(B/16) = ceil(15*B/16)
              lda abs:.word0 (viewTestA)
              cmp abs:.word0 (vtLimit)
              bcc vtStall
              lda ##VT_NATIVE
              bra vtKind
vtStall:      lda ##VT_STALL
              bra vtKind
vtStock:      lda ##VT_STOCK
vtKind:       sta abs:.word0 (viewTestKind)
vtResult:     lda ##VT_TWOTHIRDS
              ldx abs:.word0 (viewTestKind)
              cpx ##VT_STALL
              bcc vtSize
              lda ##VT_THREEQUARTERS
              cpx ##VT_STALL
              beq vtSize
              lda ##VT_FULL
vtSize:       sta abs:.word0 (viewTestSize)
              plb
              plp
              rtl
vtDead:       stz abs:.word0 (viewTestKind)   ; discard a timing interval whose count wrapped
              bra vtResult

vtStores:     sep #0x20
              ldx ##VT_PASSES
vtPassA:      STORES 0
              STORES 8
              STORES 16
              STORES 24
              dex
              bne vtPassA
              rep #0x20
              rts

vtIdles:      sep #0x20
              ldx ##VT_PASSES
vtPassB:      IDLES
              IDLES
              IDLES
              IDLES
              dex
              bne vtPassB
              rep #0x20
              rts

viewChosen:   .word 0xffff            ; the size that ViewDefault chose (65535: the settings named one)
viewTestA:    .word 0                 ; the batches of loop A in VT_TICS tics
viewTestB:    .word 0                 ; the batches of loop B
viewTestKind: .word 0                 ; VT_NONE to VT_NATIVE
viewTestSize: .word 0xffff            ; the size chosen (65535 before the test)
vtTic:        .word 0
vtNow:        .word 0
vtLimit:      .word 0
vtScratch:    .space 32
