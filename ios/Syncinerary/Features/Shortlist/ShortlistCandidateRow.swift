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
                    .font(AppType.subtitle)
                    .foregroundStyle(AppTheme.ink)
                MetaLabel(metaLine)
                SourceBadgesView(badges: candidate.sourceBadges)
            }

            Spacer()

            if isSelected {
                Button(
                    isMustGo ? "Remove must-go" : "Mark must-go",
                    systemImage: isMustGo ? "star.fill" : "star",
                    action: onToggleMustGo
                )
                .labelStyle(.iconOnly)
                .foregroundStyle(isMustGo ? AppTheme.violet : AppTheme.faded)
                .symbolEffect(.bounce, value: isMustGo)
                .frame(minWidth: AppLayout.minimumTapHeight, minHeight: AppLayout.minimumTapHeight)
            }

            Button(
                isSelected ? "Remove from shortlist" : "Add to shortlist",
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
                Button(isMustGo ? "Not must-go" : "Must-go", systemImage: isMustGo ? "star.slash" : "star.fill", action: onToggleMustGo)
                    .tint(AppTheme.violet)
            }
        }
        .swipeActions(edge: .trailing) {
            Button(isSelected ? "Remove" : "Add", systemImage: isSelected ? "minus" : "plus", action: onToggleSelection)
                .tint(isSelected ? AppTheme.stamp : AppTheme.jade)
        }
    }

    private var metaLine: String {
        var parts: [String] = []
        if let area = candidate.area {
            parts.append(area)
        }
        if let category = candidate.category {
            parts.append(category.replacing("_", with: " "))
        }
        return parts.joined(separator: " · ")
    }
}
