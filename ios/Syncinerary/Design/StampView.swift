import SwiftUI

/// A rubber stamp: monospaced caps inside a double rule, in stamp ink, set
/// at a slight angle because nobody stamps straight. Decorative on a card
/// (the decision is spoken through the buttons and the accessibility
/// actions); a real label everywhere else.
struct StampView: View {
    let mark: StampMark
    var scale = 1.0
    var isDecorative = true

    var body: some View {
        Text(mark.text)
            .font(.system(size: 15 * scale, design: .monospaced).weight(.bold))
            .textCase(.uppercase)
            .tracking(2 * scale)
            .foregroundStyle(mark.ink)
            .padding(.horizontal, 12 * scale)
            .padding(.vertical, 6 * scale)
            .overlay {
                Rectangle()
                    .stroke(mark.ink, lineWidth: 2 * scale)
            }
            .overlay {
                Rectangle()
                    .inset(by: -4 * scale)
                    .stroke(mark.ink, lineWidth: 1 * scale)
            }
            .rotationEffect(.degrees(mark.angle))
            .opacity(0.85)
            .accessibilityHidden(isDecorative)
    }
}

#Preview {
    VStack(spacing: 32) {
        StampView(mark: .liked)
        StampView(mark: .passed)
        StampView(mark: .mustGo)
        StampView(mark: .confirmed, scale: 0.7)
    }
    .padding(40)
    .background(AppTheme.paper)
}
