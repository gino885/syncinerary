import SwiftUI

/// Compatibility style for existing approval actions, now a single filled surface.
struct StampButtonStyle: ButtonStyle {
    var ink: Color = AppTheme.accent
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(.headline, design: .rounded))
            .foregroundStyle(AppTheme.canvas)
            .frame(maxWidth: .infinity, minHeight: 54)
            .padding(.horizontal, 16)
            .padding(.vertical, 4)
            .background(ink, in: .rect(cornerRadius: 18))
            .opacity(isEnabled ? (configuration.isPressed ? 0.86 : 1) : 0.4)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.96 : 1)
            .animation(reduceMotion ? AppTheme.fade : AppTheme.press, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == StampButtonStyle {
    static var stamp: StampButtonStyle { StampButtonStyle() }
    static func stamp(ink: Color) -> StampButtonStyle { StampButtonStyle(ink: ink) }
}
