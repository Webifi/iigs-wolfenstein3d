# Developer reference player: original IMF registers through the SB AdLib port.
# IRQ0 uses Wolf's PIT divisor 1702. The final record's delay is not waited out.
# Assemble with LLVM's i386 ELF tools; remove the 0x100-byte COM origin padding.
.intel_syntax noprefix
.code16
.text
.org 0x100
start:
    mov ax, cs
    mov ds, ax
    mov es, ax
    mov bx, 0x1000
    mov ah, 0x4a
    int 0x21
    jc error
    mov ah, 0x48
    int 0x21
    jc error
    mov [score_segment], ax
    mov dx, offset filename
    mov ax, 0x3d00
    int 0x21
    jc error
    mov bx, ax
    push ds
    mov ds, [score_segment]
    xor dx, dx
    mov cx, 65535
    mov ah, 0x3f
    int 0x21
    pop ds
    jc error
    mov [read_bytes], ax
    mov ah, 0x3e
    int 0x21
    mov es, [score_segment]
    mov ax, es:[0]
    test ax, 3
    jnz error
    test ax, ax
    jz error
    add ax, 2
    cmp ax, [read_bytes]
    ja error
    mov [score_end], ax
    mov word ptr [cursor], 2
    # Same FM mixer register setting made by Wolf's SDL_StartSB.
    mov dx, 0x224
    mov al, 0x26
    out dx, al
    inc dx
    mov al, 0xff
    out dx, al
    # Enable AdLib waveform selection, as in SDL_DetectAdLib.
    mov ax, 0x2001
    call opl_write
    mov ax, 0x3508
    int 0x21
    mov [old_offset], bx
    mov [old_segment], es
    mov dx, offset irq
    mov ax, 0x2508
    int 0x21
    cli
    mov al, 0x34
    out 0x43, al
    mov ax, 1702
    out 0x40, al
    mov al, ah
    out 0x40, al
    sti
wait:
    hlt
    cmp byte ptr [finished], 0
    je wait
    cli
    mov al, 0x36
    out 0x43, al
    xor ax, ax
    out 0x40, al
    out 0x40, al
    sti
    mov dx, [old_offset]
    mov ds, [old_segment]
    mov ax, 0x2508
    int 0x21
    mov ax, 0x4c00
    int 0x21
error:
    mov ax, 0x4c01
    int 0x21

irq:
    pusha
    push ds
    push es
    mov ax, cs
    mov ds, ax
    mov es, [score_segment]
    cmp byte ptr [finished], 0
    jne acknowledge
    cmp word ptr [delay], 0
    je event
    dec word ptr [delay]
    jnz acknowledge
event:
    mov si, [cursor]
    mov ax, es:[si]
    call opl_write
    mov ax, es:[si+2]
    mov [delay], ax
    add si, 4
    mov [cursor], si
    cmp si, [score_end]
    jae done
    test ax, ax
    jz event
    jmp acknowledge
done:
    mov byte ptr [finished], 1
acknowledge:
    mov al, 0x20
    out 0x20, al
    pop es
    pop ds
    popa
    iret

# AX holds register/value. Port reads supply AdLib's required write delays.
opl_write:
    push ax
    push cx
    push dx
    mov dx, 0x388
    out dx, al
    mov cx, 6
address_wait:
    in al, dx
    loop address_wait
    inc dx
    mov al, ah
    out dx, al
    dec dx
    mov cx, 35
data_wait:
    in al, dx
    loop data_wait
    pop dx
    pop cx
    pop ax
    ret
filename: .asciz "MUSIC.IMF"
score_segment: .word 0
read_bytes: .word 0
score_end: .word 0
cursor: .word 0
delay: .word 0
finished: .byte 0
old_offset: .word 0
old_segment: .word 0
