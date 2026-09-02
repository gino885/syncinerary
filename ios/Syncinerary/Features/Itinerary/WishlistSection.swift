import SwiftUI

struct WishlistSection: View {
    let items: [WishlistItem]

    var body: some View {
        if !items.isEmpty {
            Section {
                ForEach(items) { item in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.name)
                            .font(AppType.rowTitle)
                            .foregroundStyle(AppTheme.ink)
                        Text(item.reasonText)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.faded)
                    }
                    .padding(.vertical, AppTheme.spacingXS)
                    .accessibilityElement(children: .combine)
                }
            } header: {
                EyebrowText("Loved, not placed")
            }
            .journalRow()
        }
    }
}
