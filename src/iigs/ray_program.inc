;;; One bounded midpoint command in the generated depth-first ray program:
;;; LDA/STA scan, LDX/LDY anchors, JSL to the spacing-specific entry.
;;; A completed span skips two or six whole child commands on the stack.
RAY_INTERPOLATE_BYTES .equ 15
