;;; Initial view selection. S_VIEW values 0..3 select an explicit size;
;;; every other value invokes ViewDefault and becomes S_VIEW_NOTSET.
;;; ViewApply runs before the title song and returns twice the selected size
;;; for weaponViewIndex. ViewCollect retains the sentinel while the current
;;; size matches viewChosen; it updates only the in-memory settings image.
;;;
;;; The timing probe compares two loops in bank 2. Loop A uses 32 STA abs
;;; instructions with 8-bit A; loop B substitutes two NOPs per store. Each
;;; pass costs 133 nominal CPU cycles with a taken loop branch, and each
;;; batch contains VT_PASSES passes. I_GetTime is polled between batches.
;;; A starts on a DOC tic boundary. B uses the following VT_TICS interval;
;;; any overshoot at the end of A consumes part of B's interval.
;;;
;;; The B count selects the view. The A/B ratio additionally classifies the
;;; result as store-sensitive or not; this is a throughput heuristic, not
;;; accelerator identification. Both faster classifications select full view.
;;; A stalled clock or wrapped batch count falls back to the 2/3 view.
;;; Call with IRQs enabled: the probe preserves I, and masking interrupts can
;;; change accelerator speed. DBR=2 addresses the loops' scratch and clock.
#include "frontend.inc"
              .section viewtest, text, root, noreorder
              .public ViewApply, ViewCollect, ViewDefault
              .public viewChosen, viewTestA, viewTestB, viewTestKind, viewTestSize
              .extern I_GetTime, weaponViewIndex

VT_TICS       .equ 4                  ; nominal interval in 1/70-second DOC tics
VT_PASSES     .equ 32                 ; passes in one batch
VT_FAST       .equ 57                 ; minimum B batch count for full view
VT_TWOTHIRDS  .equ 1                  ; the sizes of S_VIEW
VT_FULL       .equ 3
VT_NONE       .equ 0                  ; classifications: invalid, slow, store-sensitive, balanced
VT_STOCK      .equ 1
VT_STALL      .equ 2
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

;;; A = the value for weaponViewIndex (twice the size). Flags and DBR are the caller's; X and Y are not.
ViewApply:    php
              sep #0x20
              lda long:SETTINGS_IN + S_VIEW
              cmp #4
              bcc vaSize                  ; the settings name a size: it wins
              lda #S_VIEW_NOTSET
              sta long:SETTINGS_IN + S_VIEW
              rep #0x20
              jsl long:ViewDefault        ; A = 1 (2/3 view) or 3 (full view)
              sta long:viewChosen
vaSize:       rep #0x20
              and ##255
              asl a
              plp
              rtl

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

;;; A = 1 (2/3 view) or 3 (full view). Flags and DBR are the caller's; X and Y are not.
ViewDefault:  php
              rep #0x30
              phb
              pea #0x0202
              plb
              plb
              stz abs:.word0 (viewTestA)
              stz abs:.word0 (viewTestB)
              lda ##VT_NONE
              sta abs:.word0 (viewTestKind)
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

vtBatchA:     sep #0x20
              ldx ##VT_PASSES
vtPassA:      STORES 0
              STORES 8
              STORES 16
              STORES 24
              dex
              bne vtPassA
              rep #0x20
              inc abs:.word0 (viewTestA)
              bne vtTimeA
              jmp abs:.word0 (vtDead)
vtTimeA:      jsl long:I_GetTime
              sec
              sbc abs:.word0 (vtTic)
              cmp ##VT_TICS
              bcs vtEndA
              jmp abs:.word0 (vtBatchA)
vtEndA:       lda abs:.word0 (vtTic)      ; advance the target epoch, including A overshoot
              clc
              adc ##VT_TICS
              sta abs:.word0 (vtTic)

vtBatchB:     sep #0x20
              ldx ##VT_PASSES
vtPassB:      IDLES
              IDLES
              IDLES
              IDLES
              dex
              bne vtPassB
              rep #0x20
              inc abs:.word0 (viewTestB)
              bne vtTimeB
              jmp abs:.word0 (vtDead)
vtTimeB:      jsl long:I_GetTime
              sec
              sbc abs:.word0 (vtTic)
              cmp ##VT_TICS
              bcs vtEndB
              jmp abs:.word0 (vtBatchB)

;;; Classify B below VT_FAST as slow. Otherwise compare A with ceil(7*B/8).
vtEndB:       lda abs:.word0 (viewTestB)
              cmp ##VT_FAST
              bcc vtStock
              lsr a
              lsr a
              lsr a
              sta abs:.word0 (vtLimit)
              lda abs:.word0 (viewTestB)
              sec
              sbc abs:.word0 (vtLimit)
              sta abs:.word0 (vtLimit)    ; B - floor(B/8) = ceil(7*B/8)
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
              lda ##VT_FULL
vtSize:       sta abs:.word0 (viewTestSize)
              plb
              plp
              rtl
vtDead:       stz abs:.word0 (viewTestKind)   ; discard a timing interval whose count wrapped
              bra vtResult

viewChosen:   .word 0xffff            ; the size that ViewDefault chose (65535: the settings named one)
viewTestA:    .word 0                 ; the batches of loop A in VT_TICS tics
viewTestB:    .word 0                 ; the batches of loop B
viewTestKind: .word 0                 ; VT_NONE to VT_NATIVE
viewTestSize: .word 0xffff            ; the size chosen (65535 before the test)
vtTic:        .word 0
vtLimit:      .word 0
vtScratch:    .space 32
