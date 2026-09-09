import SwiftUI

/// A small uppercase label that names what follows: "DAY 1", "IN SHORT".
struct EyebrowText: View {
    private let content: Text
    var color: Color = AppTheme.faded

    init(_ text: LocalizedStringKey, color: Color = AppTheme.faded) {
        self.content = Text(text)
        self.color = color
    }

    /// Server text, printed as it arrived.
    init(verbatim text: String, color: Color = AppTheme.faded) {
        self.content = Text(verbatim: text)
        self.color = color
    }

    var body: some View {
        content
            .font(AppType.mono)
            .textCase(.uppercase)
            .tracking(1.4)
            .foregroundStyle(color)
    }
}
