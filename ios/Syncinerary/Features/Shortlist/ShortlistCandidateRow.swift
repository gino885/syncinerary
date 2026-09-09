import SwiftUI

struct ShortlistCandidateRow: View {
    let candidate: CandidateCard
    let isSelected: Bool
    let isMustGo: Bool
    let onToggleSelection: () -> Void
    let onToggleMustGo: () -> Void

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text(candidate.nameCanonical)
                    .font(AppType.rowTitle)
                    .foregroundStyle(AppTheme.ink)
                MetaLabel(verbatim: metaLine)
                SourceBadgesView(badges: candidate.sourceBadges)
            }

            Spacer()

            if isSelected {
                Button(
                    isMustGo
                        ? String(localized: "Remove must-go")
                        : String(localized: "Mark must-go"),
                    systemImage: isMustGo ? "star.fill" : "star",
                    action: onToggleMustGo
                )
                .labelStyle(.iconOnly)
                .foregroundStyle(isMustGo ? AppTheme.violet : AppTheme.faded)
                .symbolEffect(.bounce, value: isMustGo)
                .frame(minWidth: AppLayout.minimumTapHeight, minHeight: AppLayout.minimumTapHeight)
            }

            Button(
                isSelected
                    ? String(localized: "Remove from shortlist")
                    : String(localized: "Add to shortlist"),
                systemImage: isSelected ? "minus" : "plus",
                action: onToggleSelection
            )
            .labelStyle(.iconOnly)
            .foregroundStyle(AppTheme.faded)
            .contentTransition(.symbolEffect(.replace))
            .frame(minWidth: AppLayout.minimumTapHeight, minHeight: AppLayout.minimumTapHeight)
        }
        .padding(.vertical, AppTheme.spacingXS)
        .buttonStyle(.borderless)
        .swipeActions(edge: .leading) {
            if isSelected {
                Button(
                    isMustGo ? String(localized: "Not must-go") : String(localized: "Must-go"),
                    systemImage: isMustGo ? "star.slash" : "star.fill",
                    action: onToggleMustGo
                )
                    .tint(AppTheme.violet)
            }
        }
        .swipeActions(edge: .trailing) {
            Button(
                isSelected ? String(localized: "Remove") : String(localized: "Add"),
                systemImage: isSelected ? "minus" : "plus",
                action: onToggleSelection
            )
                .tint(isSelected ? AppTheme.stamp : AppTheme.jade)
        }
    }

    private var metaLine: String {
        var parts: [String] = []
        if let area = candidate.area {
            parts.append(area)
        }
        if let category = candidate.category {
            let key = category.replacing("_", with: " ").capitalized
            parts.append(String(localized: String.LocalizationValue(key)))
        }
        return parts.joined(separator: " · ")
    }
}
