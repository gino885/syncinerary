import SwiftUI

struct JourneyButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(.headline, design: .rounded))
            .foregroundStyle(AppTheme.onAccent)
            .frame(maxWidth: .infinity, minHeight: 54)
            .padding(.horizontal, 16)
            .padding(.vertical, 4)
            .background(AppTheme.accent, in: .rect(cornerRadius: 18))
            .opacity(isEnabled ? (configuration.isPressed ? 0.86 : 1) : 0.4)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.96 : 1)
            .animation(reduceMotion ? AppTheme.fade : AppTheme.press, value: configuration.isPressed)
    }
}
