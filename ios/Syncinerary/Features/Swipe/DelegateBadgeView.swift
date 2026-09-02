import SwiftUI

/// The per-traveler hint in the detail sheet, with the reasoning one tap away.
struct DelegateBadgeView: View {
    let badge: DelegateBadge

    private var ink: Color {
        badge.type == "warning" ? AppTheme.stamp : AppTheme.jade
    }

    var body: some View {
        DisclosureGroup {
            Text(badge.reasoning)
                .font(.subheadline)
                .foregroundStyle(AppTheme.faded)
                .padding(.top, AppTheme.spacingXS)
        } label: {
            Text(badge.text)
                .font(AppType.subtitle)
                .foregroundStyle(ink)
        }
        .tint(AppTheme.faded)
    }
}
