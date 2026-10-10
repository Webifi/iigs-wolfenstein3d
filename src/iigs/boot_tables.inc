;;; Boot tables built instead of loaded (tools/registered_loads.py boot_rows,
;;; boot_built). Each builder writes the exact bytes of the file its tool
;;; writes; tools/check_boot_tables.py runs this code in tools/emu816.py and
;;; compares every byte. JSR from BuildRayPartial: native mode, A/X/Y 16 bits,
;;; DBR = this bank, interrupts off. The word products ($06-$07) are built and
;;; the boot loader has read the logic bank and tables.bin. Registers are not
;;; kept; the direct page bytes BT_DP..BT_DP+BT_DP_BYTES-1 are put back.
              .extern scaleHeight, scaleIndex, scaleWidthRecip, horizontalBase
BT_DP         .equ BOOT_TABLES_DP         ; 64 direct page bytes, saved in btSave
BT_DP_BYTES   .equ 64
BT_I          .equ BT_DP+0x00
BT_V          .equ BT_DP+0x02
BT_HALF       .equ BT_DP+0x04
BT_TOP        .equ BT_DP+0x06
BT_BOT        .equ BT_DP+0x08
BT_T          .equ BT_DP+0x0a
BT_D2         .equ BT_DP+0x0c             ; midpoints: 2d
BT_DEL        .equ BT_DP+0x0e             ; midpoints: delta
BT_2DEL       .equ BT_DP+0x10
BT_QHI        .equ BT_DP+0x12             ; q * 256; q is the byte at +1, +2 is spare
BT_SP         .equ BT_DP+0x16             ; 3-byte pointers: scaleIndex + l + r,
BT_OP         .equ BT_DP+0x1a             ;   row L of the midpoints,
BT_MP         .equ BT_DP+0x1e             ;   entry (R, L); +3 is spare
BT_END        .equ BT_DP+0x22
BT_L2         .equ BT_DP+0x24
BT_REC        .equ BT_DP+0x26
BT_REC2       .equ BT_DP+0x28
BT_N          .equ BT_DP+0x2a
BT_ACC        .equ BT_DP+0x2c
BT_SIGN       .equ BT_DP+0x2e
BT_XV         .equ BT_DP+0x30
BT_YV         .equ BT_DP+0x32
BT_FC         .equ BT_DP+0x34
BT_FS         .equ BT_DP+0x36
BT_SC         .equ BT_DP+0x38
BT_SS         .equ BT_DP+0x3a
BT_F          .equ BT_DP+0x3c
BT_T2         .equ BT_DP+0x3e
;;; The midpoint builder runs first: its gap tables use RAY_LOGIC_SETUP, which
;;; BuildLogicSetup fills after it.
BT_KTAB_A     .equ RAY_LOGIC_SETUP
BT_KTAB_B     .equ RAY_LOGIC_SETUP+0x200

BuildBootTables:
              phb
              tdc
              clc
              adc ##BT_DP
              tax
              ldy ##.word0 (btSave)
              lda ##BT_DP_BYTES-1
              .byte 0x54, .byte2 btSave, 0x00   ; MVN: the direct page bytes to btSave
              phk
              plb
              jsr abs:.word0 (BuildMidpoints)
              jsr abs:.word0 (BuildRowCode)
              jsr abs:.word0 (BuildLogicSetup)
              jsr abs:.word0 (BuildThrust)
              jsr abs:.word0 (BuildHorizontal)
              jsr abs:.word0 (BuildRayFixed)
              jsr abs:.word0 (BuildEndpoints)
              ldx ##WEIGHT_DIRECTORY-RAY_FIXED  ; the view group loads the directory; the
              lda ##0                     ;   pad and the seeds are zero, as in ray-fixed.bin
btPadZero:    sta long:RAY_FIXED,x
              inx
              inx
              cpx ##RAY_SETUP-RAY_FIXED
              bcc btPadZero
              tdc
              clc
              adc ##BT_DP
              tay
              ldx ##.word0 (btSave)
              lda ##BT_DP_BYTES-1
              .byte 0x54, 0x00, .byte2 btSave   ; MVN: btSave back to the direct page
              plb
              rts

;;; ROWCODE (gen_scalers.py rowcode.bin): for each scaler height 161 words, the
;;; code address of each screen row: the scaler's entry (scaleEntry) for rows
;;; 0..top, 7 more for each row up to bottom, then the same to row 160.
;;; top = max(0, 80-h/2), bottom = min(160, 80+h/2).
BuildRowCode: ldx ##0                     ; offset in ROWCODE
              stz dp:BT_I                 ; 2 * height index
brHeight:     phx
              ldx dp:BT_I
              lda abs:.word0 (scaleEntry),x
              sta dp:BT_V
              lda long:scaleHeight,x
              lsr a
              sta dp:BT_HALF
              plx
              lda ##80
              sec
              sbc dp:BT_HALF
              bcs brTop
              lda ##0
brTop:        sta dp:BT_TOP
              inc a
              tay                         ; rows 0..top
              lda dp:BT_V
brHead:       sta long:ROWCODE,x
              inx
              inx
              dey
              bne brHead
              lda ##80
              clc
              adc dp:BT_HALF
              cmp ##160
              bcc brBottom
              lda ##160
brBottom:     sta dp:BT_BOT
              sec
              sbc dp:BT_TOP
              tay                         ; rows top+1..bottom
              lda dp:BT_V
brBody:       clc
              adc ##7
              sta long:ROWCODE,x
              inx
              inx
              dey
              bne brBody
              sta dp:BT_V
              lda ##160
              sec
              sbc dp:BT_BOT
              beq brNext
              tay                         ; rows bottom+1..160
              lda dp:BT_V
brTail:       sta long:ROWCODE,x
              inx
              inx
              dey
              bne brTail
brNext:       lda dp:BT_I
              inc a
              inc a
              sta dp:BT_I
              cmp ##SCALER_HEIGHTS*2
              bcc brHeight
              rts

;;; RAY_MIDPOINT (gen_ray_height.py ray-midpoint.bin): row L holds 256 words for
;;; R = 0..255 of the pair l = scaleHeight[L], r = scaleHeight[min(R, 199)]:
;;; the low byte is the index of the height nearest (l+r)/2 (scaleIndex), the
;;; high byte the texel gap min(255, 3(l+r) / 2|l-r|), 255 when l = r. The table
;;; is symmetric: each entry (L, R), R > L, is also stored at (R, L). Along R > L
;;; the gap only falls: with d = r-l and T = 3(l+r) - 2qd, q is the largest gap
;;; <= 255 with T >= 0. A step to R adds 3 delta - (2q-3) delta to T (delta =
;;; r - the previous r, 2d grows by 2 delta), and each lower q adds 2d. The
;;; scaler heights rise by delta A, then from index btB2/2 on by delta B (a
;;; third step size would fail tools/check_boot_tables.py); a K table holds
;;; (2q-3) delta for q = 0..255 for each. Heights are even, so l+r is the
;;; scaleIndex offset of (l+r)/2.
BuildMidpoints:
              lda long:scaleHeight+2      ; the two steps of the heights
              sec
              sbc long:scaleHeight
              sta dp:BT_DEL
              ldx ##2
bmFindB:      inx
              inx
              lda long:scaleHeight,x
              sec
              sbc long:scaleHeight-2,x
              cmp dp:BT_DEL
              beq bmFindB
              stx abs:.word0 (btB2)       ; 2 * the first index of step B
              sta abs:.word0 (btDelB)
              lda dp:BT_DEL
              sta abs:.word0 (btDelA)
              asl a
              sta dp:BT_T                 ; 2 delta A
              lda abs:.word0 (btDelB)
              asl a
              sta dp:BT_T2                ; 2 delta B
              lda dp:BT_DEL               ; q = 0: -3 delta A
              asl a
              clc
              adc dp:BT_DEL
              eor ##0xffff
              inc a
              tay
              lda abs:.word0 (btDelB)     ; and -3 delta B
              asl a
              clc
              adc abs:.word0 (btDelB)
              eor ##0xffff
              inc a
              ldx ##0                     ; 2q
bmKTable:     sta long:BT_KTAB_B,x
              clc
              adc dp:BT_T2
              pha
              tya
              sta long:BT_KTAB_A,x
              clc
              adc dp:BT_T
              tay
              pla
              inx
              inx
              cpx ##512
              bcc bmKTable
              stz dp:BT_L2                ; 2 * L
bmRow:        lda dp:BT_L2                ; row L: (L & 127) * 512, bank +1 from 128
              xba
              and ##0xff00
              sta dp:BT_OP
              lda dp:BT_L2
              cmp ##256
              lda ##RAY_MIDPOINT>>16
              adc ##0
              sta dp:BT_OP+2
              ldx dp:BT_L2                ; R = L: l, its index, the gap 255
              lda long:scaleHeight,x
              asl a
              sta dp:BT_T                 ; 2l
              tax
              lda long:scaleIndex,x       ; scaleIndex[l]: offset 2l
              lsr a
              ora ##0xff00
              ldy dp:BT_L2
              sta [dp:BT_OP],y
              lda dp:BT_T
              clc
              adc ##.word0 (scaleIndex)
              sta dp:BT_SP                ; scaleIndex + l + r, r = l
              lda ##.byte2 scaleIndex
              sta dp:BT_SP+2
              lda dp:BT_T                 ; T = 3(2l)
              asl a
              clc
              adc dp:BT_T
              sta dp:BT_T
              stz dp:BT_D2
              lda ##0xff00
              sta dp:BT_QHI
              stz dp:BT_QHI+2
              lda dp:BT_OP                ; (R, L) for R = L+1
              clc
              adc ##512
              sta dp:BT_MP
              lda dp:BT_OP+2
              adc ##0
              sta dp:BT_MP+2
              lda dp:BT_MP
              clc
              adc dp:BT_L2
              sta dp:BT_MP
              ldx ##510                   ; 2q
              ldy dp:BT_L2                ; 2R
              cpy ##SCALER_HEIGHTS*2-2
              bcs bmFill
              tya                         ; the steps of delta A: R+1 < btB2/2
              clc
              adc ##2
              cmp abs:.word0 (btB2)
              bcs bmPartB
              lda abs:.word0 (btB2)
              dec a
              dec a
              sta dp:BT_END
              lda abs:.word0 (btDelA)
              sta dp:BT_DEL
              asl a
              sta dp:BT_2DEL
              lda ##.word0 (BT_KTAB_A)
              sta abs:.word0 (bmK+1)
              jsr abs:.word0 (bmWalk)
bmPartB:      lda ##SCALER_HEIGHTS*2-2
              sta dp:BT_END
              lda abs:.word0 (btDelB)
              sta dp:BT_DEL
              asl a
              sta dp:BT_2DEL
              lda ##.word0 (BT_KTAB_B)
              sta abs:.word0 (bmK+1)
              jsr abs:.word0 (bmWalk)
bmFill:       ldy ##(SCALER_HEIGHTS-1)*2  ; R = 200..255 repeat R = 199
              lda [dp:BT_OP],y
bmFillLoop:   iny
              iny
              sta [dp:BT_OP],y
              cpy ##510
              bcc bmFillLoop
              lda dp:BT_L2
              inc a
              inc a
              sta dp:BT_L2
              cmp ##SCALER_HEIGHTS*2
              bcs bmDone
              jmp abs:.word0 (bmRow)
bmDone:       rts

;;; Steps R = Y/2+1 .. BT_END/2 with one delta; X = 2q carries over.
bmWalk:       cpy dp:BT_END
              bcs bmWalkDone
bmStep:       iny
              iny
              lda dp:BT_SP
              clc
              adc dp:BT_DEL
              sta dp:BT_SP                ; l + r
              lda dp:BT_D2
              clc
              adc dp:BT_2DEL
              sta dp:BT_D2                ; 2d
              lda dp:BT_T
              sec
bmK:          sbc long:BT_KTAB_A,x        ; - (2q-3) delta (the table is patched)
              bpl bmGap
bmLower:      dec dp:BT_QHI+1             ; q - 1
              dex
              dex
              clc
              adc dp:BT_D2
              bmi bmLower
bmGap:        sta dp:BT_T
              lda [dp:BT_SP]
              lsr a
              ora dp:BT_QHI
              sta [dp:BT_OP],y
              sta [dp:BT_MP]
              lda dp:BT_MP
              clc
              adc ##512
              sta dp:BT_MP
              bcc bmSameBank
              inc dp:BT_MP+2
bmSameBank:   cpy dp:BT_END
              bcc bmStep
bmWalkDone:   rts

;;; RAY_LOGIC_SETUP (gen_ray_tables.py ray-logic-setup.bin).
;;; TANGENT: 900 records. The step is FINETAN of the logic bank; then twice each
;;; of its four bytes, then the negated step. Zeros up to the end of TANGENT.
BuildLogicSetup:
              ldx ##0                     ; 4 * angle
blTangent:    lda long:LOGIC_BASE+FINETAN,x
              sta dp:BT_V
              lda long:LOGIC_BASE+FINETAN+2,x
              sta dp:BT_T
              phx
              txa
              asl a
              asl a
              tax                         ; 16 * angle
              lda dp:BT_V
              sta long:TANGENT,x
              and ##255
              asl a
              sta long:TANGENT+4,x
              lda dp:BT_V
              xba
              and ##255
              asl a
              sta long:TANGENT+6,x
              lda dp:BT_T
              sta long:TANGENT+2,x
              and ##255
              asl a
              sta long:TANGENT+8,x
              lda dp:BT_T
              xba
              and ##255
              asl a
              sta long:TANGENT+10,x
              lda dp:BT_V
              eor ##0xffff
              clc
              adc ##1
              sta long:TANGENT+12,x
              lda dp:BT_T
              eor ##0xffff
              adc ##0
              sta long:TANGENT+14,x
              plx
              inx
              inx
              inx
              inx
              cpx ##TANGENT_RECORDS*4
              bcc blTangent
              ldx ##TANGENT_RECORDS*16
              lda ##0
blTanZero:    sta long:TANGENT,x
              inx
              inx
              cpx ##TANGENT_SIZE
              bcc blTanZero
;;; 3600 fine-angle records of 8 bytes after TANGENT: x*16, y*16, the flags and
;;; the sign of y. In quadrant k, i = 0..899: x = 899-i (k even) or i (k odd),
;;; y = 899-x. Flags: quadFlags (4 when x falls, 2 when y rises), and 16 when
;;; x <= 1 or x >= 898 (max(x,y) >= 898), else 8 when x <= 449 (y >= 450).
              ldx ##0                     ; record offset
              stz dp:BT_I                 ; 2 * quadrant
blQuad:       ldy dp:BT_I
              lda abs:.word0 (quadFlags),y
              sta dp:BT_TOP
              lda abs:.word0 (quadSign),y
              sta dp:BT_BOT
              ldy ##0                     ; i
blFine:       sty dp:BT_V                 ; x
              lda dp:BT_I
              and ##2                     ; an odd quadrant: x = i
              bne blX
              lda ##899
              sec
              sbc dp:BT_V
              sta dp:BT_V
blX:          lda dp:BT_V
              cmp ##2
              bcc blF16
              cmp ##898
              bcs blF16
              cmp ##450
              bcc blF8
              lda ##0
              bra blFlag
blF16:        lda ##16
              bra blFlag
blF8:         lda ##8
blFlag:       ora dp:BT_TOP
              sta long:TANGENT_END+4,x
              lda dp:BT_BOT
              sta long:TANGENT_END+6,x
              lda dp:BT_V
              asl a
              asl a
              asl a
              asl a
              sta long:TANGENT_END,x
              lda ##899
              sec
              sbc dp:BT_V
              asl a
              asl a
              asl a
              asl a
              sta long:TANGENT_END+2,x
              txa
              clc
              adc ##8
              tax
              iny
              cpy ##900
              bcc blFine
              lda dp:BT_I
              inc a
              inc a
              sta dp:BT_I
              cmp ##8
              bcs blQuadsDone
              jmp abs:.word0 (blQuad)
blQuadsDone:  lda ##0                     ; zeros up to COS_ROWS
blFineZero:   sta long:TANGENT_END,x
              inx
              inx
              cpx ##COS_ROWS-TANGENT_END
              bcc blFineZero
;;; COS_ROWS, SIN_ROWS: the word-products row page of |cos| and |sin| from
;;; COS_TABLE and SIN_TABLE (tables.bin: round(trig * 256)), 0 for 1.0. Both
;;; pairs are adjacent (tools/check_boot_tables.py).
              ldx ##0
blRows:       lda long:COS_TABLE,x
              bpl blRowAbs
              eor ##0xffff
              inc a
blRowAbs:     cmp ##256
              beq blRowOne
              asl a
              clc
              adc ##(WORD_PRODUCTS>>8)
              bra blRowSet
blRowOne:     lda ##0
blRowSet:     sta long:COS_ROWS,x
              inx
              inx
              cpx ##COS_TABLE_SIZE+SIN_TABLE_SIZE
              bcc blRows
;;; CONTROL_RECORDS: one record of 8 words per control command c: the three axes
;;; (bits 8/4, 2/1, 256/512; 35, or 70 with bit 128), bit 32, bit 64, a demo
;;; bit, bit 16, a demo bit. Demo packet p uses records 4p+j: words 5 and 7
;;; carry its bits 2j and 2j+1 (command bits 2j+2 and 2j+3); record 4p+1 has
;;; the lowest pressed weapon instead (command bits 6-9, $FFFF for none).
              ldx ##0                     ; 16 * command
              ldy ##0                     ; command
blCommand:    sty dp:BT_I
              tya
              and ##128
              beq blWalk
              lda ##70
              bra blSpeed
blWalk:       lda ##35
blSpeed:      sta dp:BT_V
              lda ##8
              ldy ##4
              jsr abs:.word0 (blAxis)
              sta long:CONTROL_RECORDS,x
              lda ##2
              ldy ##1
              jsr abs:.word0 (blAxis)
              sta long:CONTROL_RECORDS+2,x
              lda ##256
              ldy ##512
              jsr abs:.word0 (blAxis)
              sta long:CONTROL_RECORDS+4,x
              lda ##32
              jsr abs:.word0 (blBit)
              sta long:CONTROL_RECORDS+6,x
              lda ##64
              jsr abs:.word0 (blBit)
              sta long:CONTROL_RECORDS+8,x
              lda ##16
              jsr abs:.word0 (blBit)
              sta long:CONTROL_RECORDS+12,x
              lda dp:BT_I
              and ##3
              asl a
              tay                         ; 2 * j
              lda abs:.word0 (demoBitA),y
              jsr abs:.word0 (blBit)
              sta long:CONTROL_RECORDS+10,x
              lda abs:.word0 (demoBitB),y
              jsr abs:.word0 (blBit)
              sta long:CONTROL_RECORDS+14,x
              cpy ##2
              bne blNextCommand
              lda ##64
              ldy ##0
blWeapon:     bit dp:BT_I
              bne blWeaponSet
              asl a
              iny
              cpy ##4
              bcc blWeapon
              ldy ##0xffff
blWeaponSet:  tya
              sta long:CONTROL_RECORDS+10,x
blNextCommand:txa
              clc
              adc ##16
              tax
              ldy dp:BT_I
              iny
              cpy ##1024
              bcs blCommandsDone
              jmp abs:.word0 (blCommand)
blCommandsDone:
;;; SHOOT_CHANCE_1 and SHOOT_CHANCE_4: 16/d and 64/d for each distance byte d
;;; (0 for d = 0), then one zero pad byte for the word load.
              sep #0x20
              lda #0
              sta long:SHOOT_CHANCE_1
              sta long:SHOOT_CHANCE_4
              sta long:SHOOT_CHANCE_4+256
              rep #0x20
              ldx ##1
blChance:     stx dp:BT_HALF
              lda ##16
              jsr abs:.word0 (btDivide)
              sep #0x20
              sta long:SHOOT_CHANCE_1,x
              rep #0x20
              lda ##64
              jsr abs:.word0 (btDivide)
              sep #0x20
              sta long:SHOOT_CHANCE_4,x
              rep #0x20
              inx
              cpx ##256
              bcc blChance
              rts

;;; A = the positive bit, Y = the negative bit of the command BT_I: A = the
;;; axis, the speed BT_V times (positive - negative).
blAxis:       sty dp:BT_T2
              and dp:BT_I
              beq blAxisPos
              lda dp:BT_V
blAxisPos:    sta dp:BT_T
              lda dp:BT_T2
              and dp:BT_I
              beq blAxisDone
              lda dp:BT_T
              sec
              sbc dp:BT_V
              rts
blAxisDone:   lda dp:BT_T
              rts

;;; A = a bit: A = 1 when the command BT_I has it, else 0.
blBit:        and dp:BT_I
              beq blBitDone
              lda ##1
blBitDone:    rts

;;; A / BT_HALF by subtraction, for small quotients: A = the quotient. Y is used.
btDivide:     ldy ##0
btDivLoop:    cmp dp:BT_HALF
              bcc btDivDone
              sbc dp:BT_HALF
              iny
              bra btDivLoop
btDivDone:    tya
              rts

;;; THRUST_INDEX, THRUST_ROWS, THRUST_MAIN, THRUST_EXTRA (gen_ray_tables.py):
;;; per control speed n its row offset (12 times its place in thrustControls,
;;; $FFFF for any other n); per row its vectors' address and its speed; per row
;;; and degree a the vector x = FixedByFrac(speed, SINTAB[a+90]), y =
;;; -FixedByFrac(speed, SINTAB[a]) and a byte of their signs (1 x, 2 y).
;;; FixedByFrac: the speed times the fraction word, the high word, then the
;;; sign of SINTAB. Rows 0-5 go to THRUST_MAIN, rows 6-9 to THRUST_EXTRA.
BuildThrust:  ldx ##0
              lda ##0xffff
btIndexFill:  sta long:THRUST_INDEX,x
              inx
              inx
              cpx ##THRUST_CONTROL_MAX*2+2
              bcc btIndexFill
              ldy ##0                     ; 2 * place
btIndexSet:   lda abs:.word0 (thrustControls),y
              asl a
              tax
              tya
              asl a
              sta dp:BT_T
              asl a
              clc
              adc dp:BT_T                 ; 12 * place
              sta long:THRUST_INDEX,x
              iny
              iny
              cpy ##THRUST_CONTROLS*2
              bcc btIndexSet
              stz dp:BT_TOP               ; 6 * row
              stz dp:BT_BOT               ; 2 * row
              lda ##.word0 (THRUST_MAIN)
              sta dp:BT_V
              lda ##THRUST_MAIN>>16
              sta dp:BT_HALF
btRowLoop:    lda dp:BT_BOT
              cmp ##THRUST_MAIN_ROWS*2
              bne btRowBase
              lda ##.word0 (THRUST_EXTRA)
              sta dp:BT_V
              lda ##THRUST_EXTRA>>16
              sta dp:BT_HALF
btRowBase:    ldx dp:BT_TOP
              lda dp:BT_V
              sta long:THRUST_ROWS,x
              lda dp:BT_HALF
              sta long:THRUST_ROWS+2,x
              ldy dp:BT_BOT
              lda abs:.word0 (thrustSpeeds),y
              sta long:THRUST_ROWS+4,x
              sta dp:BT_I
              and ##255                   ; the product rows of the speed's bytes
              jsr abs:.word0 (btProductRow)
              sta abs:.word0 (btMulA+1)
              sta abs:.word0 (btMulC+1)
              sep #0x20
              txa
              sta abs:.word0 (btMulA+3)
              sta abs:.word0 (btMulC+3)
              rep #0x20
              lda dp:BT_I
              xba
              and ##255
              jsr abs:.word0 (btProductRow)
              sta abs:.word0 (btMulB+1)
              sta abs:.word0 (btMulE+1)
              sep #0x20
              txa
              sta abs:.word0 (btMulB+3)
              sta abs:.word0 (btMulE+3)
              lda dp:BT_HALF
              sta abs:.word0 (btPutX+3)
              sta abs:.word0 (btPutY+3)
              sta abs:.word0 (btPutSign+3)
              rep #0x20
              lda dp:BT_V
              sta abs:.word0 (btPutX+1)
              inc a
              inc a
              sta abs:.word0 (btPutY+1)
              inc a
              inc a
              sta abs:.word0 (btPutSign+1)
              stz dp:BT_N                 ; 4 * degree
              stz dp:BT_ACC               ; 5 * degree
btAngle:      ldx dp:BT_N
              lda long:LOGIC_BASE+SINTAB+THRUST_QUARTER*4,x
              sta dp:BT_FC
              lda long:LOGIC_BASE+SINTAB+THRUST_QUARTER*4+2,x
              sta dp:BT_SC
              lda long:LOGIC_BASE+SINTAB,x
              sta dp:BT_FS
              lda long:LOGIC_BASE+SINTAB+2,x
              sta dp:BT_SS
              stz dp:BT_SIGN
              lda dp:BT_FC
              jsr abs:.word0 (btMul)
              beq btCos                   ; zero stays positive
              bit dp:BT_SC
              bpl btCos
              eor ##0xffff
              inc a
              inc dp:BT_SIGN              ; 1: x < 0
btCos:        sta dp:BT_XV
              lda dp:BT_FS
              jsr abs:.word0 (btMul)
              beq btSin
              bit dp:BT_SS
              bmi btSin                   ; y = -(-m)
              eor ##0xffff
              inc a
              inc dp:BT_SIGN
              inc dp:BT_SIGN              ; 2: y < 0
btSin:        sta dp:BT_YV
              lda dp:BT_SIGN
              ldx dp:BT_ACC
;;; The sign as a word: its high byte is the next record's first byte, written
;;; next, or the zero byte after the last record.
btPutSign:    sta long:THRUST_MAIN+4,x
              lda dp:BT_XV
btPutX:       sta long:THRUST_MAIN,x
              lda dp:BT_YV
btPutY:       sta long:THRUST_MAIN+2,x
              txa
              clc
              adc ##5
              sta dp:BT_ACC
              lda dp:BT_N
              clc
              adc ##4
              sta dp:BT_N
              cmp ##THRUST_DEGREES*4
              bcs btAnglesDone
              jmp abs:.word0 (btAngle)
btAnglesDone: lda dp:BT_V
              clc
              adc ##THRUST_DEGREES*5
              sta dp:BT_V
              lda dp:BT_TOP
              clc
              adc ##6
              sta dp:BT_TOP
              lda dp:BT_BOT
              inc a
              inc a
              sta dp:BT_BOT
              cmp ##THRUST_ROW_COUNT*2
              bcs btDone
              jmp abs:.word0 (btRowLoop)
btDone:       rts

;;; A = a byte b: A = the low word, X = the bank of the word-products row of b.
btProductRow: pha
              and ##127
              xba
              asl a
              clc
              adc ##.word0 (WORD_PRODUCTS)
              tay
              pla
              and ##128
              beq btRowLow
              ldx ##(WORD_PRODUCTS>>16)+1
              tya
              rts
btRowLow:     ldx ##WORD_PRODUCTS>>16
              tya
              rts

;;; A = F: A = (speed * F) >> 16 from four word products (rows patched to the
;;; speed's low byte, A and C, and high byte, B and E); Z for a zero result.
btMul:        sta dp:BT_F
              and ##255
              asl a
              tax                         ; 2 * the low byte of F
btMulA:       lda long:WORD_PRODUCTS,x
              xba
              and ##255
              sta dp:BT_T                 ; (low * low) >> 8
btMulB:       lda long:WORD_PRODUCTS,x
              sta dp:BT_T2                ; high * low
              lda dp:BT_F
              xba
              and ##255
              asl a
              tax                         ; 2 * the high byte of F
btMulC:       lda long:WORD_PRODUCTS,x    ; low * high
              clc
              adc dp:BT_T
              clc
              adc dp:BT_T2                ; carry: bit 16
              xba
              and ##255
              bcc btMulCarry
              ora ##256
btMulCarry:   sta dp:BT_T
btMulE:       lda long:WORD_PRODUCTS,x    ; high * high
              clc
              adc dp:BT_T
              rts

;;; HORIZONTAL (gen_scalers.py horizontal.bin): for each scaler height h, at
;;; horizontalBase, h/2 bytes min(63, (scaleWidthRecip * column) >> 8), written
;;; two at a time; an odd count's spare byte is the next height's first byte,
;;; written after it (the last height has an even count).
BuildHorizontal:
              ldx ##0                     ; 2 * height index
bhHeight:     stx dp:BT_I
              lda long:scaleWidthRecip,x
              sta dp:BT_REC
              asl a
              sta dp:BT_REC2
              lda long:scaleHeight,x
              lsr a
              inc a
              lsr a
              tay                         ; words: the columns / 2, rounded up
              lda long:horizontalBase,x
              tax
              stz dp:BT_ACC
bhPair:       lda dp:BT_ACC
              cmp ##0x4000                ; from 64 * 256 every byte is 63
              bcs bhRest
              xba
              and ##255
              sta dp:BT_T
              lda dp:BT_ACC
              clc
              adc dp:BT_REC
              cmp ##0x4000
              bcs bhHigh63
              and ##0xff00
              bra bhPut
bhHigh63:     lda ##0x3f00
bhPut:        ora dp:BT_T
              sta long:HORIZONTAL,x
              inx
              inx
              lda dp:BT_ACC
              clc
              adc dp:BT_REC2
              sta dp:BT_ACC
              dey
              bne bhPair
              bra bhNext
bhRest:       lda ##0x3f3f
bhFill:       sta long:HORIZONTAL,x
              inx
              inx
              dey
              bne bhFill
bhNext:       ldx dp:BT_I
              inx
              inx
              cpx ##SCALER_HEIGHTS*2
              bcc bhHeight
              rts

;;; RAY_FIXED (gen_ray_height.py ray-fixed.bin, gen_ray_tables.py ray-setup.bin): the span
;;; heights scaleIndex[h >> 3] for h = 0..5120 at RAY_SPAN_HEIGHT, then RAY_SETUP: per angle
;;; a (1024) 8 words: DX, DY, STEPX, STEPY, the partial-row pages of DX and DY, the wall-DDA
;;; slot, 2*DY. DX and its row are seed entry fold(a) (|cos| repeats every 512 angles and
;;; mirrors at 256), DY those of a-256. STEPX is -128 for a = 257..768, STEPY -2 for
;;; a = 1..512: the signs of the generator's floating point cos and -sin. The slot is
;;; $8000 + 256 (4 for STEPX < 0, 2 for STEPY > 0, 1 for DX >= DY). 2*DY stops at $FFFF.
;;; BuildBootTables zeroes WEIGHT_DIRECTORY up to RAY_SETUP after the seeds are used.
BuildRayFixed:
              ldx ##0                     ; 2 * (h >> 3)
              ldy ##0                     ; 2h
rfSpan:       lda long:scaleIndex,x
              phx
              tyx
              sta long:RAY_SPAN_HEIGHT,x
              sta long:RAY_SPAN_HEIGHT+2,x
              sta long:RAY_SPAN_HEIGHT+4,x
              sta long:RAY_SPAN_HEIGHT+6,x
              sta long:RAY_SPAN_HEIGHT+8,x
              sta long:RAY_SPAN_HEIGHT+10,x
              sta long:RAY_SPAN_HEIGHT+12,x
              sta long:RAY_SPAN_HEIGHT+14,x
              txa
              clc
              adc ##16
              tay
              plx
              inx
              inx
              cpx ##(RAY_SPAN_HEIGHT_SIZE-2)/8
              bcc rfSpan
              lda long:scaleIndex,x       ; the last span height
              tyx
              sta long:RAY_SPAN_HEIGHT,x
              ldx ##0                     ; 16 * angle
              ldy ##0                     ; angle
rsAngle:      sty dp:BT_I
              tya
              jsr abs:.word0 (rsFold)
              sta dp:BT_V                 ; fold(a)
              tya
              sec
              sbc ##256
              and ##1023
              jsr abs:.word0 (rsFold)
              sta dp:BT_T                 ; fold(a - 256)
              phx
              lda dp:BT_V
              asl a
              tax
              lda long:BOOT_TABLE_SEEDS,x
              sta dp:BT_XV                ; DX
              lda dp:BT_T
              asl a
              tax
              lda long:BOOT_TABLE_SEEDS,x
              sta dp:BT_YV                ; DY
              ldx dp:BT_V
              lda long:BOOT_TABLE_SEEDS+SEED_ROWS,x
              and ##255
              asl a
              clc
              adc ##RAY_PARTIAL>>8
              sta dp:BT_FC                ; the page of DX's row
              ldx dp:BT_T
              lda long:BOOT_TABLE_SEEDS+SEED_ROWS,x
              and ##255
              asl a
              clc
              adc ##RAY_PARTIAL>>8
              sta dp:BT_FS                ; DY's
              plx
              lda dp:BT_XV
              sta long:RAY_SETUP,x
              lda dp:BT_YV
              sta long:RAY_SETUP+2,x
              lda dp:BT_FC
              sta long:RAY_SETUP+8,x
              lda dp:BT_FS
              sta long:RAY_SETUP+10,x
              lda ##0x8000
              sta dp:BT_SIGN              ; the slot
              lda ##128
              ldy dp:BT_I
              cpy ##257
              bcc rsXPos
              cpy ##769
              bcs rsXPos
              lda ##0x0400
              tsb dp:BT_SIGN
              lda ##0xff80
rsXPos:       sta long:RAY_SETUP+4,x
              lda ##0xfffe
              cpy ##1
              bcc rsYPos
              cpy ##513
              bcc rsYNeg
rsYPos:       lda ##0x0200
              tsb dp:BT_SIGN
              lda ##2
rsYNeg:       sta long:RAY_SETUP+6,x
              lda dp:BT_XV
              cmp dp:BT_YV
              bcc rsSlot
              lda ##0x0100
              tsb dp:BT_SIGN
rsSlot:       lda dp:BT_SIGN
              sta long:RAY_SETUP+12,x
              lda dp:BT_YV
              asl a
              bcc rs2DY
              lda ##0xffff
rs2DY:        sta long:RAY_SETUP+14,x
              txa
              clc
              adc ##16
              tax
              iny
              cpy ##1024
              bcs rsDone
              jmp abs:.word0 (rsAngle)
rsDone:       rts

;;; A = an angle 0..1023: A = its place in the seeds, 0..256.
rsFold:       and ##511
              cmp ##257
              bcc rsFolded
              eor ##0xffff
              sec
              adc ##512                   ; 512 - a
rsFolded:     rts

;;; ENDPOINTS (gen_scalers.py sprite-endpoints.bin): one 256-byte page per scaler
;;; height h (w = h/2, r = scaleWidthRecip): bytes 0..64 the screen row of texel row
;;; t, max(0, min(160, 80 - h/2 + (t*h + 63) >> 6)); words at 65 for t = 0..64 the
;;; column min(w, ceil(256t / r)), w for t = 64; zeros to 199; the 16 pool endpoint
;;; bytes from the seeds; at 216 for each view size v (viewSizes) the side limit
;;; (s*256 + w - 1) / w with left = (v - w) / 2 rounded down and s = max(v - left,
;;; left + w); zeros to 255.
BuildEndpoints:
              stz dp:BT_N                 ; page offset
              stz dp:BT_I                 ; 2 * height index
beHeight:     ldx dp:BT_I
              lda long:scaleHeight,x
              sta dp:BT_V                 ; h
              lsr a
              sta dp:BT_HALF              ; w
              lda long:scaleWidthRecip,x
              sta dp:BT_REC
              lda dp:BT_V                 ; the row rises by h/64 per texel row:
              lsr a                       ;   the whole part, and the fraction in 64ths
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:BT_D2
              lda dp:BT_V
              and ##63
              sta dp:BT_T2
              lda ##80
              sec
              sbc dp:BT_HALF
              sta dp:BT_TOP               ; the row, 80 - h/2 + (63 >> 6), signed
              lda ##63
              sta dp:BT_ACC               ; the fraction of t*h + 63, in 64ths
              ldx dp:BT_N
              ldy ##65
beRow:        lda dp:BT_TOP
              bpl beRowLow
              lda ##0
beRowLow:     cmp ##161
              bcc beRowPut
              lda ##160
beRowPut:     sep #0x20
              sta long:ENDPOINTS,x
              rep #0x20
              inx
              lda dp:BT_ACC
              clc
              adc dp:BT_T2
              cmp ##64
              bcc beRowFrac
              sbc ##64
              inc dp:BT_TOP
beRowFrac:    sta dp:BT_ACC
              lda dp:BT_TOP
              clc
              adc dp:BT_D2
              sta dp:BT_TOP
              dey
              bne beRow
              lda ##256                   ; ceil(256t / r) = (256t + r - 1) / r rises by
              sta dp:BT_F                 ;   256 / r per step: the quotient and the rest
              lda dp:BT_REC
              sta dp:BT_SC
              phx
              jsr abs:.word0 (btDiv16)
              plx
              sta dp:BT_FS                ; 256 / r
              lda dp:BT_T2
              sta dp:BT_FC                ; 256 mod r
              stz dp:BT_D2                ; q
              lda dp:BT_REC
              dec a
              sta dp:BT_ACC               ; the rest of r - 1
              ldy ##64
beInv:        lda dp:BT_D2
              cmp dp:BT_HALF
              bcc beInvPut
              lda dp:BT_HALF
beInvPut:     sta long:ENDPOINTS,x
              inx
              inx
              lda dp:BT_D2
              clc
              adc dp:BT_FS
              sta dp:BT_D2
              lda dp:BT_ACC
              clc
              adc dp:BT_FC
              cmp dp:BT_REC
              bcc beInvRest
              sbc dp:BT_REC
              inc dp:BT_D2
beInvRest:    sta dp:BT_ACC
              dey
              bne beInv
              lda dp:BT_HALF              ; t = 64
              sta long:ENDPOINTS,x
              lda ##0                     ; bytes 195..199
              sta long:ENDPOINTS+2,x
              sta long:ENDPOINTS+4,x
              sta long:ENDPOINTS+5,x
              lda dp:BT_I                 ; the pool bytes: seed 16n
              asl a
              asl a
              asl a
              clc
              adc ##SEED_POOLS
              tay
              ldx dp:BT_N
              lda ##8
              sta dp:BT_T2
bePool:       phx
              tyx
              lda long:BOOT_TABLE_SEEDS,x
              plx
              sta long:ENDPOINTS+200,x
              inx
              inx
              iny
              iny
              dec dp:BT_T2
              bne bePool
              ldy ##0                     ; 2 * view
beLimit:      lda abs:.word0 (viewSizes),y
              sta dp:BT_SC                ; v
              sec
              sbc dp:BT_HALF
              cmp ##0x8000
              ror a                       ; left = (v - w) / 2, rounded down
              sta dp:BT_FC
              lda dp:BT_SC
              sec
              sbc dp:BT_FC
              sta dp:BT_F                 ; v - left
              lda dp:BT_FC
              clc
              adc dp:BT_HALF              ; left + w
              cmp dp:BT_F
              bcc beLimitMax
              sta dp:BT_F
beLimitMax:   lda dp:BT_F                 ; s < 256
              xba
              and ##0xff00
              clc
              adc dp:BT_HALF
              dec a
              sta dp:BT_F                 ; s*256 + w - 1
              lda dp:BT_HALF
              sta dp:BT_SC
              phy
              jsr abs:.word0 (btDiv16)
              ply
              pha
              tya
              clc
              adc dp:BT_N
              tax
              pla
              sta long:ENDPOINTS+216,x
              iny
              iny
              cpy ##8
              bcc beLimit
              ldx dp:BT_N                 ; bytes 224..255
              ldy ##16
              lda ##0
beTail:       sta long:ENDPOINTS+224,x
              inx
              inx
              dey
              bne beTail
              lda dp:BT_N
              clc
              adc ##256
              sta dp:BT_N
              lda dp:BT_I
              inc a
              inc a
              sta dp:BT_I
              cmp ##SCALER_HEIGHTS*2
              bcs beDone
              jmp abs:.word0 (beHeight)
beDone:       rts

;;; BT_F / BT_SC, 16 bits by 16 bits: A = BT_F = the quotient. BT_T2 and Y are used.
btDiv16:      stz dp:BT_T2
              ldy ##16
bdLoop:       asl dp:BT_F
              rol dp:BT_T2
              lda dp:BT_T2
              cmp dp:BT_SC
              bcc bdNext
              sbc dp:BT_SC
              sta dp:BT_T2
              inc dp:BT_F
bdNext:       dey
              bne bdLoop
              lda dp:BT_F
              rts

TANGENT_RECORDS .equ 900                  ; FINEANGLES/4
THRUST_CONTROLS .equ 5
THRUST_CONTROL_MAX .equ 280
THRUST_ROW_COUNT .equ 10
THRUST_MAIN_ROWS .equ 6
THRUST_DEGREES .equ 360
THRUST_QUARTER .equ 90                    ; cos a = SINTAB[a+90]
quadFlags:    .word 0, 4, 6, 2
quadSign:     .word 0xffff, 0xffff, 1, 1
demoBitA:     .word 4, 16, 64, 256
demoBitB:     .word 8, 32, 128, 512
thrustControls:.word 35, 70, 100, 140, 280
thrustSpeeds: .word 3500, 5250, 7000, 10500, 10000, 15000, 14000, 21000, 28000, 42000
btB2:         .word 0
btDelA:       .word 0
btDelB:       .word 0
btSave:       .space BT_DP_BYTES
#include "scaler_entries.inc"
#include "boot_seeds.inc"
