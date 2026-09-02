import SwiftUI

struct PreferenceSummaryRow: View {
    let summary: String

    var body: some View {
        HStack(spacing: AppTheme.spacingM) {
            VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
                Text("Choose what sounds like you")
                    .foregroundStyle(AppTheme.ink)
                Text(summary)
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.faded)
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .foregroundStyle(AppTheme.faded)
                .accessibilityHidden(true)
        }
        .frame(minHeight: AppLayout.minimumTapHeight)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens preference choices")
    }
}

#Preview {
    PreferenceSummaryRow(summary: "Local food, Coffee · 1 food avoid")
        .padding()
        .background(AppTheme.paper)
}
