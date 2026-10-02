import SwiftUI

/// Rounded display, readable body, and aligned clock figures.
/// Semantic text styles keep every role responsive to Dynamic Type.
enum AppType {
    static let title = Font.system(.largeTitle, design: .rounded, weight: .heavy)
    static let name = Font.system(.title, design: .rounded, weight: .bold)
    static let dayDate = Font.system(.title2, design: .rounded, weight: .bold)
    static let rowTitle = Font.headline
    static let body = Font.body
    static let stampText = Font.system(.footnote, design: .rounded, weight: .bold)
    static let mono = Font.system(.footnote, design: .monospaced)
    static let monoBody = Font.system(.body, design: .monospaced)
}
