"""Build the 4-bit fade lookup using nearest perceptual gray lightness."""


def gray_lightness(nibble):
    """CIELAB L* for the sRGB gray displayed by the native capture renderer."""
    encoded = nibble / 15
    linear = encoded / 12.92 if encoded <= 0.04045 else ((encoded + 0.055) / 1.055) ** 2.4
    return 116 * linear ** (1 / 3) - 16 if linear > 216 / 24389 else linear * 24389 / 27


def fade_table():
    lightness = [gray_lightness(value) for value in range(16)]
    # Nearest-level quantization avoids the black delay from truncation. The
    # endpoints and neutral hues remain exact; no temporal flicker is added.
    return [
        [min(range(value + 1), key=lambda shade: abs(lightness[shade] - lightness[value] * step / 16))
         for value in range(16)]
        for step in range(17)
    ]
