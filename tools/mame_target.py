"""Stock IIgs with a 4 MiB expansion card, including onboard fast RAM."""

def ram_size(machine):
    return '5M' if machine == 'apple2gs' else '4352K'
