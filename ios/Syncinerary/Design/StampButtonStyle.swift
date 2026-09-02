import SwiftUI

/// The primary action on a screen: ink on paper inside a stamp's double
/// rule, so pressing it reads as stamping the page. One per screen.
struct StampButtonStyle: ButtonStyle {
    var ink: Color = AppTheme.stamp

    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(AppType.stampText)
            .textCase(.uppercase)
            .tracking(2)
            .foregroundStyle(ink)
            .frame(maxWidth: .infinity, minHeight: 50)
            .overlay {
                Rectangle().stroke(ink, lineWidth: 2)
            }
            .overlay {
                Rectangle().inset(by: -4).stroke(ink, lineWidth: 1)
            }
            .padding(4)
            .opacity(isEnabled ? (configuration.isPressed ? 0.5 : 1) : 0.35)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(AppTheme.stampDown, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == StampButtonStyle {
    static var stamp: StampButtonStyle { StampButtonStyle() }
    static func stamp(ink: Color) -> StampButtonStyle { StampButtonStyle(ink: ink) }
}
