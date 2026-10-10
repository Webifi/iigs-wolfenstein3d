(load "build/gen/memmap.scm")
(define memories
  `((memory FixedGen (address (,SEG_FIXED_GEN . ,SEG_FIXED_GEN_LAST))
            (section fixedgen))
    ))
