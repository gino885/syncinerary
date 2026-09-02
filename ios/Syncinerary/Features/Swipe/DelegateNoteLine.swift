import SwiftUI

/// The hint for this traveler, written in the margin: a rule, then the line.
struct DelegateNoteLine: View {
    let badge: DelegateBadge

    private var ink: Color {
        badge.type == "warning" ? AppTheme.stamp : AppTheme.jade
    }

    var body: some View {
        HStack(alignment: .top, spacing: AppTheme.spacingS) {
            Rectangle()
                .fill(ink)
                .frame(width: 2)
                .accessibilityHidden(true)
            Text(badge.text)
                .font(.subheadline)
                .italic()
                .foregroundStyle(ink)
                .lineLimit(2)
        }
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityLabel(badge.type == "warning" ? "Warning: \(badge.text)" : badge.text)
    }
}
