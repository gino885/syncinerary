import SwiftUI

/// One monospaced line of facts: "SAPPORO · PARK · 90 MIN".
struct MetaLabel: View {
    private let content: Text
    var color: Color = AppTheme.faded

    init(_ text: LocalizedStringKey, color: Color = AppTheme.faded) {
        self.content = Text(text)
        self.color = color
    }

    /// For a line assembled from server data. Printed as it arrived, never
    /// looked up, so a place name is not mistaken for a translatable phrase.
    init(verbatim text: String, color: Color = AppTheme.faded) {
        self.content = Text(verbatim: text)
        self.color = color
    }

    var body: some View {
        content
            .font(AppType.mono)
            .monospacedDigit()
            .textCase(.uppercase)
            .foregroundStyle(color)
            .lineLimit(2)
    }
}
