import SwiftUI

struct ReplanDiffRow: View {
    let systemImage: String
    let title: String
    let detail: String
    let tint: Color

    var body: some View {
        HStack(alignment: .top, spacing: AppTheme.spacingS) {
            Rectangle()
                .fill(tint)
                .frame(width: 2)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(AppType.subtitle)
                    .foregroundStyle(AppTheme.ink)
                MetaLabel(detail)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .padding(.vertical, AppTheme.spacingXS)
        .accessibilityElement(children: .combine)
    }
}
