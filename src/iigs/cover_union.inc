;;; Absorb touching entries into this run, retaining descending bottoms.
;;; CV_I has already walked to its upper edge; revisit only the overlap.
UN_TOP        .equ AI_TMP
UN_BOTTOM     .equ AI_FAMILY
UN_END        .equ AI_COUNT

              .section buffersave, text, root, noreorder
coverUnion:   sta dp:UN_BOTTOM
              lda dp:RN_T
              sta dp:UN_TOP
              ldx dp:CV_I
              beq unionInsert
              lda abs:.word0 (coverList-1),x
              and ##255
              cmp dp:RN_T
              bcs unionCandidate
              dex
              dex
unionCandidate:
              stx dp:UN_END
              cpx ##0
              beq unionInsert
              lda abs:.word0 (coverList-2),x
              and ##255
              cmp dp:RN_B
              bcc unionMerge
              beq unionMerge
unionInsert:  stx dp:UN_END
              ldx dp:CV_N
              cpx dp:UN_END
              beq unionPlace
unionShift:   lda abs:.word0 (coverList-2),x
              sta abs:.word0 (coverList),x
              dex
              dex
              cpx dp:UN_END
              bne unionShift
unionPlace:   lda dp:RN_B
              xba
              ora dp:RN_T
              sta abs:.word0 (coverList),x
              inx
              inx
              stx dp:CV_I
              inc dp:CV_N
              inc dp:CV_N
              lda dp:RN_T
              jmp abs:.word0 (runGhost)

unionMerge:   cmp dp:UN_TOP
              bcs unionBottom
              sta dp:UN_TOP
unionBottom:  lda abs:.word0 (coverList-1),x
              and ##255
              cmp dp:UN_BOTTOM
              bcc unionLower
              sta dp:UN_BOTTOM
unionLower:   dex
              dex
              beq unionMerged
              lda abs:.word0 (coverList-2),x
              and ##255
              cmp dp:UN_BOTTOM
              bcc unionMerge
              beq unionMerge
unionMerged:  stx dp:CV_I
              lda dp:UN_BOTTOM
              xba
              ora dp:UN_TOP
              sta abs:.word0 (coverList),x
              inx
              inx
              cpx dp:UN_END
              beq unionDone
              ldy dp:UN_END
              cpy dp:CV_N
              beq unionShortened
unionTail:    lda abs:.word0 (coverList),y
              sta abs:.word0 (coverList),x
              inx
              inx
              iny
              iny
              cpy dp:CV_N
              bcc unionTail
unionShortened:
              stx dp:CV_N
unionDone:    lda dp:RN_T
              jmp abs:.word0 (runGhost)
