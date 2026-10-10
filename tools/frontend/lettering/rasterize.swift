import Foundation
import CoreGraphics
import CoreText

// Mixed-case, hard-edged rasterization for the heading proposals; build-time only.
// usage: swift render_font_mixed.swift FONT.ttf CAP_HEIGHT OUTPUT.json
// Every glyph keeps the same rows (top of the tallest ink down to the lowest
// descender) so a baseline index is shared by the whole face.
let args = CommandLine.arguments
let sizeMode = args.count >= 4 && args[2].hasSuffix("pt")
guard args.count >= 4, let capHeight = Double(sizeMode ? String(args[2].dropLast(2)) : args[2]) else {
    fatalError("usage: swift render_font_mixed.swift FONT.ttf CAP_HEIGHT OUTPUT.json")
}
let descriptors = CTFontManagerCreateFontDescriptorsFromURL(URL(fileURLWithPath: args[1]) as CFURL) as! [CTFontDescriptor]
let probe = CTFontCreateWithFontDescriptor(descriptors[0], 100, nil)
var probeChar = UniChar(72)
var probeGlyph = CGGlyph()
CTFontGetGlyphsForCharacters(probe, &probeChar, &probeGlyph, 1)
let probeBox = CTFontGetBoundingRectsForGlyphs(probe, .default, &probeGlyph, nil, 1)
let size = sizeMode ? capHeight : 100 * capHeight / probeBox.height   // a point size, or the height of the ink of H
let font = CTFontCreateWithFontDescriptor(descriptors[0], size, nil)
let side = 96
let baseline = 32
var bitmaps: [Int: [UInt8]] = [:]
let wanted = Set(Array("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!?&.,:;-+/()'\"".unicodeScalars.map { Int($0.value) }))
let everything = args.count >= 5 && args[4] == "all"
for code in 33...126 where everything || wanted.contains(code) {
    var character = UniChar(code)
    var glyph = CGGlyph()
    guard CTFontGetGlyphsForCharacters(font, &character, &glyph, 1) else { continue }
    var pixels = [UInt8](repeating: 0, count: side * side)
    pixels.withUnsafeMutableBytes { buffer in
        let context = CGContext(data: buffer.baseAddress, width: side, height: side,
                                bitsPerComponent: 8, bytesPerRow: side,
                                space: CGColorSpaceCreateDeviceGray(), bitmapInfo: 0)!
        context.setAllowsAntialiasing(false)
        context.setShouldAntialias(false)
        context.setAllowsFontSmoothing(false)
        context.setShouldSmoothFonts(false)
        context.setAllowsFontSubpixelPositioning(false)
        context.setShouldSubpixelPositionFonts(false)
        context.setAllowsFontSubpixelQuantization(false)
        context.setShouldSubpixelQuantizeFonts(false)
        context.setFillColor(gray: 1, alpha: 1)
        var position = CGPoint(x: 16, y: baseline)
        CTFontDrawGlyphs(font, &glyph, &position, 1, context)
    }
    bitmaps[code] = pixels
}
var top = side, bottom = 0
for (_, p) in bitmaps {
    for y in 0..<side { for x in 0..<side where p[y * side + x] > 127 { top = min(top, y); bottom = max(bottom, y) } }
}
var output: [String: Any] = [:]
for (code, p) in bitmaps {
    var xs: [Int] = []
    for y in top...bottom { for x in 0..<side where p[y * side + x] > 127 { xs.append(x) } }
    guard let minX = xs.min(), let maxX = xs.max() else { continue }
    output[String(UnicodeScalar(code)!)] = (top...bottom).map { y in
        (minX...maxX).map { x in p[y * side + x] > 127 ? "#" : "." }.joined()
    }
}
// row index of the baseline inside the glyph rows; the context origin is bottom-left
let baselineRow = (side - baseline) - top
let data = try JSONSerialization.data(withJSONObject: ["cap_height": Int(capHeight), "rows": bottom - top + 1,
    "baseline_row": baselineRow, "point_size": size, "postscript_name": CTFontCopyPostScriptName(font),
    "glyphs": output], options: [.sortedKeys, .prettyPrinted])
try data.write(to: URL(fileURLWithPath: args[3]))
