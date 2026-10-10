#include "memmap.inc"
#include "frontend.inc"
              .section gamecode, text, root, noreorder
              .public BenchDivide, BenchMultiply
              .extern dvA, dvB, dvR, mulA, mulB
BenchDivide:     stz abs:.word0 (dvR)
              stz abs:.word0 (dvR + 2)
              ldy ##32
divideBit:    asl abs:.word0 (dvA)
              rol abs:.word0 (dvA + 2)
              rol abs:.word0 (dvR)
              rol abs:.word0 (dvR + 2)
              lda abs:.word0 (dvR + 2)
              cmp abs:.word0 (dvB + 2)
              bcc divideNext
              bne divideSub
              lda abs:.word0 (dvR)
              cmp abs:.word0 (dvB)
              bcc divideNext
divideSub:    lda abs:.word0 (dvR)
              sec
              sbc abs:.word0 (dvB)
              sta abs:.word0 (dvR)
              lda abs:.word0 (dvR + 2)
              sbc abs:.word0 (dvB + 2)
              sta abs:.word0 (dvR + 2)
              inc abs:.word0 (dvA)
divideNext:   dey
              bne divideBit
              rtl

BenchMultiply: lda abs:.word0 (dvA)
              sta abs:.word0 (mulA)
              lda abs:.word0 (dvA + 2)
              sta abs:.word0 (mulA + 2)
              stx abs:.word0 (mulB)
              stz abs:.word0 (dvA)
              stz abs:.word0 (dvA + 2)
mulBit:       lda abs:.word0 (mulB)
              beq mulDone
              lsr a
              sta abs:.word0 (mulB)
              bcc mulShift
              lda abs:.word0 (dvA)
              clc
              adc abs:.word0 (mulA)
              sta abs:.word0 (dvA)
              lda abs:.word0 (dvA + 2)
              adc abs:.word0 (mulA + 2)
              sta abs:.word0 (dvA + 2)
mulShift:     asl abs:.word0 (mulA)
              rol abs:.word0 (mulA + 2)
              bra mulBit
mulDone:      rtl


              .public BenchClock, BenchPaintCore
              .extern benchLast, benchSlowest, benchTics, benchRow, benchY, benchLabels, benchOut, sReturn
              .extern BenchDrawLeft, BenchDrawRight, BenchDrawCenter, DrawTitleCore
;;; A is the DOC tic at the completed frame. The last timestamp is taken
;;; before demoFinished resets the world, so reset work is not a slow frame.
BenchClock:   pha
              sec
              sbc abs:.word0 (benchLast)
              cmp abs:.word0 (benchSlowest)
              bcc benchAccumulate
              sta abs:.word0 (benchSlowest)
benchAccumulate: clc
              adc abs:.word0 (benchTics)
              sta abs:.word0 (benchTics)
              bcc benchSame
              inc abs:.word0 (benchTics + 2)
benchSame:    pla
              sta abs:.word0 (benchLast)
              rtl

BenchPaintCore:   lda ##.word0 (UI_STAGE + 0x1800)
              sta dp:U_SRC
              lda ##5
              sta dp:U_Y
              jsl long:DrawTitleCore
              stz abs:.word0 (benchRow)
benchPaintRow: lda abs:.word0 (benchRow)
              asl a
              tax
              lda abs:.word0 (benchLabels),x
              sta dp:U_STR
              jsr abs:.word0 (benchPosition)
              lda ##24
              sta dp:U_X
              jsl long:BenchDrawLeft
              jsr abs:.word0 (benchPosition)
              lda abs:.word0 (benchY)
              sec
              sbc ##40
              clc
              adc ##.word0 (benchOut)
              sta dp:U_STR
              lda ##296
              sta dp:U_X
              jsl long:BenchDrawRight
              inc abs:.word0 (benchRow)
              lda abs:.word0 (benchRow)
              cmp ##10
              bcc benchPaintRow
              lda ##.word0 (sReturn)
              sta dp:U_STR
              lda ##160
              sta dp:U_X
              lda ##150
              sta dp:U_Y
              jsl long:BenchDrawCenter
              rtl
benchPosition: lda abs:.word0 (benchRow)
              asl a
              asl a
              sta dp:U_T0
              asl a
              asl a
              clc
              adc ##40
              sta abs:.word0 (benchY)
              sec                         ; 16-byte records; rows are 11 pixels apart
              sbc dp:U_T0
              sbc abs:.word0 (benchRow)
              sta dp:U_Y
              stz dp:U_FONT
              lda ##C_GRAY
              sta dp:U_C
              rts


              .public BenchTextCore
              .extern benchFrames, sMachine, sSeconds, sMs, sPoint, weaponViewIndex, viewNames
              .extern BenchNumOut, BenchNum32Out, BenchOut, BenchDiv16
              .extern CpuText
;;; Ten fixed-width value records; labels and numeric units stay separate.
BenchTextCore:    lda ##.word0 (benchOut)
              sta dp:U_OUT
              lda ##.word0 (sMachine)
              jsr abs:.word0 (benchAdd)
              lda long:ROMVER
              and ##255
              jsr abs:.word0 (benchNum)
              lda ##.word0 (benchOut + 16)
              sta dp:U_OUT
              lda long:weaponViewIndex
              tax
              lda abs:.word0 (viewNames),x
              jsr abs:.word0 (benchAdd)
              lda ##.word0 (benchOut + 32)
              sta dp:U_OUT
              lda abs:.word0 (benchFrames)
              jsr abs:.word0 (benchNum)
              lda ##.word0 (benchOut + 48)
              sta dp:U_OUT
              jsr abs:.word0 (benchTotal)
              lda ##7
              jsr abs:.word0 (divide)
              jsr abs:.word0 (benchTenths)
              lda ##.word0 (sSeconds)
              jsr abs:.word0 (benchAdd)
              lda ##.word0 (benchOut + 64)
              sta dp:U_OUT
              jsr abs:.word0 (benchTotal)
              ldx ##1000
              jsr abs:.word0 (scale)
              lda ##70
              jsr abs:.word0 (divide)
              lda abs:.word0 (benchFrames)
              jsr abs:.word0 (divide)
              jsr abs:.word0 (benchMs)
              lda ##.word0 (benchOut + 80)
              sta dp:U_OUT
              lda abs:.word0 (benchSlowest)
              ldx ##1000
              jsr abs:.word0 (multiply)
              lda ##70
              jsr abs:.word0 (divide)
              jsr abs:.word0 (benchMs)
              lda ##.word0 (benchOut + 96)
              sta dp:U_OUT
              lda abs:.word0 (benchFrames)
              ldx ##7000
              jsr abs:.word0 (multiply)
              lda abs:.word0 (benchTics)
              sta abs:.word0 (dvB)
              lda abs:.word0 (benchTics + 2)
              sta abs:.word0 (dvB + 2)
              jsr abs:.word0 (divideBy)
              lda ##100
              jsr abs:.word0 (divide)
              lda abs:.word0 (dvR)
              pha
              jsr abs:.word0 (benchNum32)
              lda ##.word0 (sPoint)
              jsr abs:.word0 (benchAdd)
              pla
              ldx ##10
              jsl long:BenchDiv16
              phx
              jsr abs:.word0 (benchNum)
              pla
              jsr abs:.word0 (benchNum)
              jmp long:CpuText
benchTotal:   lda abs:.word0 (benchTics)
              sta abs:.word0 (dvA)
              lda abs:.word0 (benchTics + 2)
              sta abs:.word0 (dvA + 2)
              rts
benchMs:      jsr abs:.word0 (benchNum32)
              lda ##.word0 (sMs)
              jmp abs:.word0 (benchAdd)
benchTenths:  lda ##10
              jsr abs:.word0 (divide)
              lda abs:.word0 (dvR)
              pha
              jsr abs:.word0 (benchNum32)
              lda ##.word0 (sPoint)
              jsr abs:.word0 (benchAdd)
              pla
              jmp abs:.word0 (benchNum)

benchNum:     jsl long:BenchNumOut
              rts
benchNum32:   lda abs:.word0 (dvA)
              sta dp:U_T0
              lda abs:.word0 (dvA + 2)
              sta dp:U_T1
              jsl long:BenchNum32Out
              rts
benchAdd:     sta dp:U_STR
              jsl long:BenchOut
              rts

divide:       sta abs:.word0 (dvB)
              stz abs:.word0 (dvB + 2)
divideBy:     jsl long:BenchDivide
              rts
multiply:     sta abs:.word0 (dvA)
              stz abs:.word0 (dvA + 2)
scale:        jsl long:BenchMultiply
              rts

