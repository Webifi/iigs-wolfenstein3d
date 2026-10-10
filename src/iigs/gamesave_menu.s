;;; Near menu entries bridge to the cold save engine in bank 2.
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public SaveWorld
              .extern SaveWorldCore
              .extern progressExtra, progressTotal, ProgressAdd, ProgressRemaining, busyShown, busyKind
              .extern NeedHomeDisk, FindHomeDisk, ReleaseDisk, BusyShow, BusyBar, BusyHide, UiTime, ShowNote, SoundStop
              .public SaveProgressSize, SaveNeedHomeDisk, SaveReleaseDisk, SaveFindHome, SaveBusyShow, SaveBusyBar, SaveBusyHide, SaveUiTime, SaveShowNote, SaveSoundStop

SaveWorld:    jsl long:SaveWorldCore
              rts
SaveNeedHomeDisk: jsr abs:.word0 (NeedHomeDisk)
              rtl
SaveReleaseDisk: jsr abs:.word0 (ReleaseDisk)
              rtl
SaveFindHome: jsr abs:.word0 (FindHomeDisk)
              rtl
SaveBusyShow: pha
              ora abs:.word0 (busyKind)
              bne saveShowNow
              lda abs:.word0 (progressExtra)
              beq saveShowNow
              lda abs:.word0 (busyShown)
              beq saveShowNow
              pla
              rtl
saveShowNow:  pla
              jsr abs:.word0 (BusyShow)
              rtl
SaveBusyBar: lda abs:.word0 (progressExtra)
              beq saveOrdinaryBar
              lda dp:U_DONE
              cmp abs:.word0 (saveProgressLast)
              bcs saveProgressDelta
              stz abs:.word0 (saveProgressLast)
saveProgressDelta:
              sec
              sbc abs:.word0 (saveProgressLast)
              beq saveBarOut
              pha
              lda dp:U_DONE
              sta abs:.word0 (saveProgressLast)
              lda dp:U_UNIT
              and ##0x70
              cmp ##0x50
              bne saveReadHD
              pla
              asl a
              sta abs:.word0 (saveProgressTemp)
              asl a
              asl a
              asl a
              clc
              adc abs:.word0 (saveProgressTemp)
              bra saveReadCredit
saveReadHD:    pla
              inc a
saveReadCredit:
              jsl long:ProgressAdd
saveBarOut:   rtl
saveOrdinaryBar:
              jsr abs:.word0 (BusyBar)
              rtl
SaveProgressSize:
              lda abs:.word0 (progressExtra)
              beq saveBarOut
              lda dp:U_TOTAL
              beq saveBarOut
              dec a                       ; the blocks after the first, one read
              pha
              lda dp:U_UNIT
              and ##0x70
              cmp ##0x50
              bne saveSizeHD
              pla
              asl a
              sta abs:.word0 (saveProgressTemp)
              asl a
              asl a
              asl a
              clc
              adc abs:.word0 (saveProgressTemp)
              bra saveSizeTail
saveSizeHD:   pla
              asl a
saveSizeTail: clc
              adc ##300
              jsl long:ProgressRemaining
              rtl
SaveBusyHide: lda abs:.word0 (progressExtra)
              bne saveBarOut
              jsr abs:.word0 (BusyHide)
              rtl
SaveUiTime: jsr abs:.word0 (UiTime)
              rtl
SaveShowNote: pha
              jsr abs:.word0 (BusyHide)
              pla
              jsr abs:.word0 (ShowNote)
              rtl
SaveSoundStop: jsr abs:.word0 (SoundStop)
              rtl

              .section menudata, data, root
saveProgressLast:.word 0
saveProgressTemp:.word 0
