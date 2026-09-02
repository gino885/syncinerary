import SwiftUI

/// Three voices. The display serif is a *display* face with thin hairlines,
/// so it is only ever set large: a screen's title, a place's name, a day's
/// date. Anything at reading size uses the system face, which is built for
/// it, and anything with digits uses the system monospaced face.
enum AppType {
    /// Instrument Serif, bundled under the SIL OFL (see Design/Fonts).
    /// `relativeTo` keeps it on Dynamic Type.
    private static func serif(_ size: Double, relativeTo textStyle: Font.TextStyle) -> Font {
        .custom("InstrumentSerif-Regular", size: size, relativeTo: textStyle)
    }

    // MARK: Display, serif, never below 24pt

    /// A screen's own title.
    static let title = serif(38, relativeTo: .largeTitle)
    /// A place's name, and the one big number on a summary line.
    static let name = serif(30, relativeTo: .title)
    /// The date at the head of an itinerary day.
    static let dayDate = serif(24, relativeTo: .title2)

    // MARK: Reading sizes, system face

    /// Every list row's title. Semibold so it holds its own against the
    /// monospaced line of facts underneath it.
    static let rowTitle = Font.headline
    /// A line the reader is meant to read, not scan.
    static let body = Font.body

    // MARK: Figures and stamps

    static let stampText = Font.system(.footnote, design: .monospaced).weight(.semibold)
    static let mono = Font.system(.footnote, design: .monospaced)
    static let monoBody = Font.system(.body, design: .monospaced)
}
