import SwiftUI

struct LodgingOptionRow: View {
    let option: LodgingOption
    let isSelected: Bool

    var body: some View {
        HStack(alignment: .top, spacing: AppTheme.spacingM) {
            VStack(alignment: .leading, spacing: 2) {
                Text(option.name)
                    .font(AppType.rowTitle)
                    .foregroundStyle(AppTheme.ink)
                MetaLabel(metaLine)
                if let address = option.address {
                    Text(address)
                        .font(.footnote)
                        .foregroundStyle(AppTheme.faded)
                }
            }

            Spacer()

            Image(systemName: isSelected ? "checkmark.square.fill" : "square")
                .font(.title2)
                .foregroundStyle(isSelected ? AppTheme.jade : AppTheme.rule)
                .contentTransition(.symbolEffect(.replace))
                .accessibilityHidden(true)
        }
        .padding(.vertical, AppTheme.spacingXS)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
        .accessibilityValue(isSelected ? "Selected" : "Not selected")
    }

    private var metaLine: String {
        var parts: [String] = []
        if let area = option.area {
            parts.append(area)
        }
        parts.append(String(repeating: "$", count: max(1, option.priceTier)))
        return parts.joined(separator: " · ")
    }
}
