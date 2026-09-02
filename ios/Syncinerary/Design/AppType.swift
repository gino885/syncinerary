import SwiftUI

/// Three voices: a bundled display serif for names and titles, the system
/// face for reading, and the system monospaced face for anything with digits
/// or anything set as a stamp.
enum AppType {
    /// Instrument Serif, bundled under the SIL OFL (see Design/Fonts).
    /// `relativeTo` keeps it on Dynamic Type.
    static func display(_ size: Double, relativeTo textStyle: Font.TextStyle = .largeTitle) -> Font {
        .custom("InstrumentSerif-Regular", size: size, relativeTo: textStyle)
    }

    static let title = display(38, relativeTo: .largeTitle)
    static let name = display(28, relativeTo: .title)
    static let subtitle = display(21, relativeTo: .title3)

    /// Stamp text, times, dates, counts.
    static let stampText = Font.system(.footnote, design: .monospaced).weight(.semibold)
    static let mono = Font.system(.footnote, design: .monospaced)
    static let monoBody = Font.system(.body, design: .monospaced)
}
