import SwiftUI

/// One monospaced line of facts: "SAPPORO · PARK · 90 MIN".
struct MetaLabel: View {
    let text: String
    var color: Color = AppTheme.faded

    init(_ text: String, color: Color = AppTheme.faded) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text)
            .font(AppType.mono)
            .monospacedDigit()
            .textCase(.uppercase)
            .foregroundStyle(color)
            .lineLimit(2)
    }
}
