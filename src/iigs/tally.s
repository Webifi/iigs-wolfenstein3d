;;; LevelCompleted tally. Runs only after the floor has ended, from LevelFlow.
#include "memmap.inc"
#include "game.inc"
#include "logic.inc"
#include "menu.inc"
#include "campaign.inc"
              .extern campaignPar, campaignRatioOffset, campaignLocal, campaignBonus
              .section flowcode, text, root, noreorder
              .public TallyOpen, TallyTick, TallyWait, TextAt, DrawChar
              .extern TallyPage, TallyReveal, TallyChar, TallyBreathe
              .extern levelIndex, levelStart, inputSerial, sfxEvent, flowPhase
              .extern tallyBonus, tallyKill, tallySecret, tallyTreasure
              .extern tallySec, tallyLeft, tallyPar, tallyTimePart, musicRequest
              .extern flowShownBonus, flowShown, flowStep, flowPause, flowAck, flowPaid
              .extern flowPtr, flowX, flowY, flowScr, flowBits, flowGlyph, flowRows
              .extern flowRight, flowSuffix, flowClearW, flowClearB, flowDigitStart
              .extern flowElapsed, flowNum, flowMul, flowDiv, flowPay, flowRem
              .extern flowTarget, flowNib, flowDigits
              .extern I_GetTime, LogicGivePoints, LogicPublish, UpdateHUD, PrepareMusic, StartPreparedMusic, PlaySoundEvent

;;; Right edges in screen pixels. Ratio labels already contain the percent
;;; sign, so the number formatter must not append another one.
BONUS_RIGHT   .equ 288
RATIO_RIGHT   .equ 296

TallyOpen:    phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              stz abs:.word0 (flowPaid)
              stz abs:.word0 (flowShown)
              stz abs:.word0 (flowShownBonus)
              stz abs:.word0 (flowShownBonus+2)
              stz abs:.word0 (flowStep)
              stz abs:.word0 (flowPause)
              jsl long:I_GetTime
              sec
              sbc abs:.word0 (levelStart)
              sta abs:.word0 (flowElapsed)
              txa
              sbc abs:.word0 (levelStart+2)
              sta abs:.word0 (flowElapsed+2)
              bcs elapsedOk
              stz abs:.word0 (flowElapsed)
              stz abs:.word0 (flowElapsed+2)
elapsedOk:    lda abs:.word0 (flowElapsed+2)
              cmp ##7
              bcs capSeconds
              cmp ##6
              bcc divSeconds
              lda abs:.word0 (flowElapsed)
              cmp ##0x5838              ; 99 minutes of 70 Hz tics
              bcs capSeconds
divSeconds:   stz abs:.word0 (tallySec)
div70:        lda abs:.word0 (flowElapsed+2)
              bne div70sub
              lda abs:.word0 (flowElapsed)
              cmp ##70
              bcc secondsReady
div70sub:     lda abs:.word0 (flowElapsed)
              sec
              sbc ##70
              sta abs:.word0 (flowElapsed)
              bcs div70inc
              dec abs:.word0 (flowElapsed+2)
div70inc:     inc abs:.word0 (tallySec)
              lda abs:.word0 (tallySec)
              cmp ##5940
              bcc div70
              bra secondsReady
capSeconds:   lda ##5940
              sta abs:.word0 (tallySec)
secondsReady: stz abs:.word0 (tallyPar)
              stz abs:.word0 (tallyLeft)
              lda abs:.word0 (levelIndex)
              asl a
              tax
              lda long:campaignPar,x
              sta abs:.word0 (tallyPar)
              lda abs:.word0 (tallySec)
              cmp abs:.word0 (tallyPar)
              bcs ratios
              lda abs:.word0 (tallyPar)
              sec
              sbc abs:.word0 (tallySec)
              sta abs:.word0 (tallyLeft)
ratios:       lda long:LOGIC_BASE+V_killcount
              pha
              lda long:LOGIC_BASE+V_killtotal
              tax
              pla
              jsr abs:.word0 (Percent)
              sta abs:.word0 (tallyKill)
              lda long:LOGIC_BASE+V_secretcount
              pha
              lda long:LOGIC_BASE+V_secrettotal
              tax
              pla
              jsr abs:.word0 (Percent)
              sta abs:.word0 (tallySecret)
              lda long:LOGIC_BASE+V_treasurecount
              pha
              lda long:LOGIC_BASE+V_treasuretotal
              tax
              pla
              jsr abs:.word0 (Percent)
              sta abs:.word0 (tallyTreasure)
              stz abs:.word0 (tallyTimePart)
              stz abs:.word0 (tallyTimePart+2)
              ldy abs:.word0 (tallyLeft)
              beq timePartDone
timePartAdd:  lda abs:.word0 (tallyTimePart)
              clc
              adc ##500
              sta abs:.word0 (tallyTimePart)
              bcc timePartNext
              inc abs:.word0 (tallyTimePart+2)
timePartNext: dey
              bne timePartAdd
timePartDone: lda abs:.word0 (tallyTimePart)
              sta abs:.word0 (tallyBonus)
              lda abs:.word0 (tallyTimePart+2)
              sta abs:.word0 (tallyBonus+2)
              lda abs:.word0 (tallyKill)
              cmp ##100
              bne bonusSecret
              jsr abs:.word0 (Add10000Bonus)
bonusSecret:  lda abs:.word0 (tallySecret)
              cmp ##100
              bne bonusTreasure
              jsr abs:.word0 (Add10000Bonus)
bonusTreasure:lda abs:.word0 (tallyTreasure)
              cmp ##100
              bne board
              jsr abs:.word0 (Add10000Bonus)
board:        lda ##16
              sta abs:.word0 (musicRequest)
              jsl long:PrepareMusic
              jsl long:TallyPage
              jsl long:StartPreparedMusic
              jsl long:I_GetTime
              sec
              sbc ##25
              sta abs:.word0 (flowBreath)
              stz abs:.word0 (flowPose)
              lda abs:.word0 (levelIndex)
              asl a
              tax
              lda long:campaignRatioOffset,x
              cmp ##65535
              bne floorBoard
              jmp abs:.word0 (secretBoard)
floorBoard:
              jsr abs:.word0 (TextAt)
              .word 112, 16
              .asciz "FLOOR"
              jsr abs:.word0 (TextAt)
              .word 112, 32
              .asciz "COMPLETED"
              lda ##208
              sta abs:.word0 (flowX)
              lda ##16
              sta abs:.word0 (flowY)
              lda abs:.word0 (levelIndex)
              asl a
              tax
              lda long:campaignLocal,x
              clc
              adc ##'0'
              jsr abs:.word0 (DrawChar)
              jsr abs:.word0 (TextAt)
              .word 112, 56
              .asciz "BONUS"
              jsr abs:.word0 (TextAt)
              .word 128, 80
              .asciz "TIME"
              jsr abs:.word0 (TextAt)
              .word 128, 96
              .asciz "PAR"
              jsr abs:.word0 (TextAt)
              .word 72, 112
              .asciz "KILL RATIO    %"
              jsr abs:.word0 (TextAt)
              .word 40, 128
              .asciz "SECRET RATIO    %"
              jsr abs:.word0 (TextAt)
              .word 8, 144
              .asciz "TREASURE RATIO    %"
              lda ##208
              sta abs:.word0 (flowX)
              lda ##80
              sta abs:.word0 (flowY)
              lda abs:.word0 (tallySec)
              jsr abs:.word0 (DrawClock)
              lda ##208
              sta abs:.word0 (flowX)
              lda ##96
              sta abs:.word0 (flowY)
              lda abs:.word0 (tallyPar)
              jsr abs:.word0 (DrawClock)
              stz abs:.word0 (flowPay)
              stz abs:.word0 (flowPay+2)
              stz abs:.word0 (flowSuffix)
              lda ##BONUS_RIGHT
              sta abs:.word0 (flowRight)
              lda ##56
              sta abs:.word0 (flowY)
              jsr abs:.word0 (DrawValue)
              lda ##RATIO_RIGHT
              sta abs:.word0 (flowRight)
              lda ##112
              sta abs:.word0 (flowY)
              jsr abs:.word0 (DrawValue)
              lda ##128
              sta abs:.word0 (flowY)
              jsr abs:.word0 (DrawValue)
              lda ##144
              sta abs:.word0 (flowY)
              jsr abs:.word0 (DrawValue)
              lda abs:.word0 (inputSerial)
              sta abs:.word0 (flowAck)
              bra openExit
secretBoard:  jsr abs:.word0 (TextAt)
              .word 112, 32
              .asciz "SECRET FLOOR"
              jsr abs:.word0 (TextAt)
              .word 112, 48
              .asciz "COMPLETED!"
              jsr abs:.word0 (TextAt)
              .word 80, 128
              .asciz "15000 BONUS!"
              lda abs:.word0 (levelIndex)
              asl a
              tax
              lda long:campaignBonus,x
              sta abs:.word0 (tallyBonus)
              stz abs:.word0 (tallyBonus+2)
              jsr abs:.word0 (PayBonus)
              lda abs:.word0 (inputSerial)
              sta abs:.word0 (flowAck)
              lda ##3
              sta abs:.word0 (flowPhase)
openExit:     jsl long:TallyReveal
              plb
              rts

TallyTick:    phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              lda abs:.word0 (inputSerial)
              cmp abs:.word0 (flowAck)
              bne TallyFinish
              lda abs:.word0 (flowPause)
              beq tickStage
              dec abs:.word0 (flowPause)
              bra tickOut
tickStage:    lda abs:.word0 (flowStep)
              beq tickBonus
              cmp ##4
              bcs TallyFinish
              jsr abs:.word0 (RatioTick)
              bra tickOut
tickBonus:    jsr abs:.word0 (DrawPartial)
              lda abs:.word0 (flowShown)
              ldx ##50
              jsr abs:.word0 (BonusBlip)
              lda abs:.word0 (flowShown)
              cmp abs:.word0 (tallyLeft)
              bcc bonusMore
              lda abs:.word0 (tallyTimePart)
              sta abs:.word0 (flowShownBonus)
              lda abs:.word0 (tallyTimePart+2)
              sta abs:.word0 (flowShownBonus+2)
              lda abs:.word0 (tallyLeft)
              beq bonusSilent
              lda ##12                  ; ENDBONUS2SND
              jsl long:PlaySoundEvent
bonusSilent:  lda ##8
              sta abs:.word0 (flowPause)
              inc abs:.word0 (flowStep)
              stz abs:.word0 (flowShown)
              bra tickOut
bonusMore:    clc
              adc ##5
              cmp abs:.word0 (tallyLeft)
              bcc bonusStore
              lda abs:.word0 (tallyLeft)
bonusStore:   sta abs:.word0 (flowShown)
tickOut:      plb
              rts

TallyFinish:  lda abs:.word0 (tallyBonus)
              sta abs:.word0 (flowPay)
              lda abs:.word0 (tallyBonus+2)
              sta abs:.word0 (flowPay+2)
              stz abs:.word0 (flowSuffix)
              lda ##BONUS_RIGHT
              sta abs:.word0 (flowRight)
              lda ##56
              sta abs:.word0 (flowY)
              jsr abs:.word0 (DrawValue)
              stz abs:.word0 (flowPay+2)
              lda ##RATIO_RIGHT
              sta abs:.word0 (flowRight)
              lda abs:.word0 (tallyKill)
              sta abs:.word0 (flowPay)
              lda ##112
              sta abs:.word0 (flowY)
              jsr abs:.word0 (DrawValue)
              lda abs:.word0 (tallySecret)
              sta abs:.word0 (flowPay)
              lda ##128
              sta abs:.word0 (flowY)
              jsr abs:.word0 (DrawValue)
              lda abs:.word0 (tallyTreasure)
              sta abs:.word0 (flowPay)
              lda ##144
              sta abs:.word0 (flowY)
              jsr abs:.word0 (DrawValue)
              jsr abs:.word0 (PayBonus)
              lda abs:.word0 (inputSerial)
              sta abs:.word0 (flowAck)
              lda ##3
              sta abs:.word0 (flowPhase)
              bra tickOut

TallyWait:    phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              lda abs:.word0 (inputSerial)
              cmp abs:.word0 (flowAck)
              beq waitBreathe
              lda ##4
              sta abs:.word0 (flowPhase)
              bra waitOut
;;; BJ breathes while the screen waits for a key: his two pictures alternate every 35 tics (BJ_Breathe).
waitBreathe:  jsl long:I_GetTime
              sec
              sbc abs:.word0 (flowBreath)
              cmp ##35
              bcc waitOut
              jsl long:I_GetTime
              sta abs:.word0 (flowBreath)
              lda abs:.word0 (flowPose)
              eor ##1
              sta abs:.word0 (flowPose)
              jsl long:TallyBreathe
waitOut:      plb
              rts

RatioTick:    lda abs:.word0 (flowStep)
              dec a
              asl a
              tax
              lda abs:.word0 (tallyKill),x
              sta abs:.word0 (flowTarget)
              lda abs:.word0 (ratioY),x
              sta abs:.word0 (flowY)
              stz abs:.word0 (flowPay+2)
              lda abs:.word0 (flowShown)
              sta abs:.word0 (flowPay)
              stz abs:.word0 (flowSuffix)
              lda ##RATIO_RIGHT
              sta abs:.word0 (flowRight)
              jsr abs:.word0 (DrawValue)
              lda abs:.word0 (flowShown)
              ldx ##10
              jsr abs:.word0 (BonusBlip)
              lda abs:.word0 (flowShown)
              cmp abs:.word0 (flowTarget)
              bcc ratioMore
              lda abs:.word0 (flowTarget)
              cmp ##100
              beq ratio100
              cmp ##0
              beq ratioZero
              lda ##12
              ldx ##8
              bra ratioEnd
ratio100:     jsr abs:.word0 (AddPerfect)
              lda ##14                  ; PERCENT100SND
              ldx ##35
              bra ratioEnd
ratioZero:    lda ##13                  ; NOBONUSSND
              ldx ##35
ratioEnd:     jsl long:PlaySoundEvent
              stx abs:.word0 (flowPause)
              inc abs:.word0 (flowStep)
              stz abs:.word0 (flowShown)
              rts
ratioMore:    inc abs:.word0 (flowShown)
              rts

;;; A is the value, X the modulus. A multiple stores ENDBONUS1SND.
BonusBlip:    stx abs:.word0 (flowDiv)
blipMod:      cmp abs:.word0 (flowDiv)
              bcc blipDone
              sec
              sbc abs:.word0 (flowDiv)
              bra blipMod
blipDone:     cmp ##0
              bne blipNo
              lda ##11
              jsl long:PlaySoundEvent
blipNo:       rts

DrawPartial:  stz abs:.word0 (flowPay)
              stz abs:.word0 (flowPay+2)
              ldy abs:.word0 (flowShown)
              beq partialGo
partialAdd:   lda abs:.word0 (flowPay)
              clc
              adc ##500
              sta abs:.word0 (flowPay)
              bcc partialNext
              inc abs:.word0 (flowPay+2)
partialNext:  dey
              bne partialAdd
partialGo:    stz abs:.word0 (flowSuffix)
              lda ##BONUS_RIGHT
              sta abs:.word0 (flowRight)
              lda ##56
              sta abs:.word0 (flowY)
              jmp abs:.word0 (DrawValue)

AddPerfect:   lda abs:.word0 (flowShownBonus)
              clc
              adc ##10000
              sta abs:.word0 (flowShownBonus)
              bcc perfectStore
              inc abs:.word0 (flowShownBonus+2)
perfectStore: lda abs:.word0 (flowShownBonus)
              sta abs:.word0 (flowPay)
              lda abs:.word0 (flowShownBonus+2)
              sta abs:.word0 (flowPay+2)
              stz abs:.word0 (flowSuffix)
              lda ##BONUS_RIGHT
              sta abs:.word0 (flowRight)
              lda ##56
              sta abs:.word0 (flowY)
              jmp abs:.word0 (DrawValue)

Add10000Bonus:lda abs:.word0 (tallyBonus)
              clc
              adc ##10000
              sta abs:.word0 (tallyBonus)
              bcc add10ret
              inc abs:.word0 (tallyBonus+2)
add10ret:     rts

;;; A is the count, X the total. Zero total stays zero, as in LevelCompleted.
Percent:      cpx ##0
              beq percent0
              stx abs:.word0 (flowDiv)
              sta abs:.word0 (flowNum)
              stz abs:.word0 (flowMul)
              ldy ##100
percentMul:   lda abs:.word0 (flowMul)
              clc
              adc abs:.word0 (flowNum)
              bcs percentHuge
              sta abs:.word0 (flowMul)
              dey
              bne percentMul
              ldx ##0
              lda abs:.word0 (flowMul)
percentDiv:   cmp abs:.word0 (flowDiv)
              bcc percentQuot
              sec
              sbc abs:.word0 (flowDiv)
              inx
              bra percentDiv
percentQuot:  txa
              rts
percentHuge:  lda ##100
              rts
percent0:     lda ##0
              rts

PayBonus:     lda abs:.word0 (flowPaid)
              bne payDone
              lda ##1
              sta abs:.word0 (flowPaid)
              lda abs:.word0 (tallyBonus)
              sta abs:.word0 (flowPay)
              lda abs:.word0 (tallyBonus+2)
              sta abs:.word0 (flowPay+2)
payLoop:      lda abs:.word0 (flowPay)
              ora abs:.word0 (flowPay+2)
              beq payHud
              lda abs:.word0 (flowPay+2)
              bne pay10
              lda abs:.word0 (flowPay)
              cmp ##10000
              bcc payRest
pay10:        lda abs:.word0 (flowPay)
              sec
              sbc ##10000
              sta abs:.word0 (flowPay)
              bcs payCall
              dec abs:.word0 (flowPay+2)
payCall:      lda ##10000
              jsl long:LogicGivePoints
              bra payLoop
payRest:      lda abs:.word0 (flowPay)
              jsl long:LogicGivePoints
payHud:       jsr abs:.word0 (LogicPublish)
              jsr abs:.word0 (UpdateHUD)
payDone:      rts

;;; Words, then an asciz string, follow the jsr. The data bank is 2.
TextAt:       pla
              inc a
              sta abs:.word0 (flowPtr)
              tax
              lda abs:0,x
              sta abs:.word0 (flowX)
              inx
              inx
              lda abs:0,x
              sta abs:.word0 (flowY)
              inx
              inx
textNext:     sep #0x20
              lda abs:0,x
              beq textEnd
              rep #0x20
              and ##255
              phx
              jsr abs:.word0 (DrawChar)
              plx
              inx
              bra textNext
textEnd:      rep #0x20
              phx
              rts

DrawClock:    ldx ##0
clockMin:     cmp ##60
              bcc clockSplit
              sec
              sbc ##60
              inx
              cpx ##100
              bcc clockMin
              ldx ##99
              lda ##0
clockSplit:   pha
              txa
              jsr abs:.word0 (DrawPair)
              lda ##':'
              jsr abs:.word0 (DrawChar)
              pla
DrawPair:     ldx ##0
pairTens:     cmp ##10
              bcc pairOnes
              sec
              sbc ##10
              inx
              bra pairTens
pairOnes:     pha
              txa
              clc
              adc ##'0'
              jsr abs:.word0 (DrawChar)
              pla
              clc
              adc ##'0'
              jmp abs:.word0 (DrawChar)

;;; flowPay is the value. flowRight is the right edge. flowSuffix draws %.
DrawValue:    ldx ##8
valueDigits:  lda abs:.word0 (flowPay)
              ora abs:.word0 (flowPay+2)
              beq valueZero
              jsr abs:.word0 (Rem10)
              dex
              sep #0x20
              clc
              adc #'0'
              sta abs:.word0 (flowDigits),x
              rep #0x20
              bra valueDigits
valueZero:    cpx ##8
              bne valueHave
              dex
              sep #0x20
              lda #'0'
              sta abs:.word0 (flowDigits),x
              rep #0x20
valueHave:    stx abs:.word0 (flowDigitStart)
              lda abs:.word0 (flowRight)
              sec
              sbc ##48                  ; three digits: a number only grows, and the label stays to the left
              sta abs:.word0 (flowX)
              lda ##48
              sta abs:.word0 (flowClearW)
              jsr abs:.word0 (ClearBox)
              lda ##8
              sec
              sbc abs:.word0 (flowDigitStart)
              asl a
              asl a
              asl a
              asl a
              sta abs:.word0 (flowNum)
              lda abs:.word0 (flowRight)
              sec
              sbc abs:.word0 (flowNum)
              ldx abs:.word0 (flowSuffix)
              beq valueLeft
              sec
              sbc ##16
valueLeft:    sta abs:.word0 (flowX)
              ldx abs:.word0 (flowDigitStart)
valueDraw:    cpx ##8
              bcs valueSuffix
              sep #0x20
              lda abs:.word0 (flowDigits),x
              rep #0x20
              and ##255
              phx
              jsr abs:.word0 (DrawChar)
              plx
              inx
              bra valueDraw
valueSuffix:  lda abs:.word0 (flowSuffix)
              beq valueDone
              lda ##'%'
              jsr abs:.word0 (DrawChar)
valueDone:    rts

;;; Quotient replaces flowPay. Remainder returns in A. X is kept.
Rem10:        phx
              stz abs:.word0 (flowRem)
              ldy ##32
remBit:       asl abs:.word0 (flowPay)
              rol abs:.word0 (flowPay+2)
              rol abs:.word0 (flowRem)
              lda abs:.word0 (flowRem)
              cmp ##10
              bcc remNext
              sec
              sbc ##10
              sta abs:.word0 (flowRem)
              inc abs:.word0 (flowPay)
remNext:      dey
              bne remBit
              lda abs:.word0 (flowRem)
              plx
              rts

ClearBox:     jsr abs:.word0 (ScreenAddr)
              lda abs:.word0 (flowClearW)
              lsr a
              sta abs:.word0 (flowClearB)
              lda ##16
              sta abs:.word0 (flowRows)
clearRows:    ldx abs:.word0 (flowScr)
              ldy abs:.word0 (flowClearB)
              sep #0x20
              lda #TALLY_FILL
clearBytes:   sta long:SHR,x
              inx
              dey
              bne clearBytes
              rep #0x20
              lda abs:.word0 (flowScr)
              clc
              adc ##160
              sta abs:.word0 (flowScr)
              dec abs:.word0 (flowRows)
              bne clearRows
              rts

ScreenAddr:   lda abs:.word0 (flowY)
              asl a
              asl a
              asl a
              asl a
              asl a
              sta abs:.word0 (flowScr)
              lda abs:.word0 (flowY)
              xba
              lsr a
              clc
              adc abs:.word0 (flowScr)
              sta abs:.word0 (flowScr)
              lda abs:.word0 (flowX)
              lsr a
              clc
              adc abs:.word0 (flowScr)
              sta abs:.word0 (flowScr)
              rts

;;; A = the character. The big letter goes to flowX and flowY, and flowX moves on (tally_art.s).
DrawChar:     jsl long:TallyChar
              rts

parSeconds:   .word 90, 120, 120, 210, 180, 180, 150, 150
ratioY:       .word 112, 128, 144

              .section gamedata, data, root
flowBreath:   .word 0
flowPose:     .word 0
