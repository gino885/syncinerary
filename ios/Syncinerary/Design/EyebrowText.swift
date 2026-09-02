import SwiftUI

/// A small uppercase label that names what follows: "DAY 1", "IN SHORT".
struct EyebrowText: View {
    let text: String
    var color: Color = AppTheme.faded

    init(_ text: String, color: Color = AppTheme.faded) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text)
            .font(AppType.mono)
            .textCase(.uppercase)
            .tracking(1.4)
            .foregroundStyle(color)
    }
}
