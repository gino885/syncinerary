import SwiftUI

/// A compact decision label. Its wording carries state as well as its color.
struct StampView: View {
    let mark: StampMark
    var scale = 1.0
    var isDecorative = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Text(mark.text)
            .font(scale < 1 ? .footnote.bold() : .title3.bold())
            .foregroundStyle(mark.ink)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(AppTheme.surface, in: .rect(cornerRadius: 12))
            .overlay { RoundedRectangle(cornerRadius: 12).strokeBorder(mark.ink, lineWidth: 2) }
            .rotationEffect(.degrees(reduceMotion ? 0 : mark.angle))
            .accessibilityHidden(isDecorative)
    }
}
