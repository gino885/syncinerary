import SwiftUI

struct ShortlistCandidateRow: View {
    let candidate: CandidateCard
    let isSelected: Bool
    let isMustGo: Bool
    let onToggleSelection: () -> Void
    let onToggleMustGo: () -> Void

    var body: some View {
        HStack {
            VStack(alignment: .leading) {
                Text(candidate.nameCanonical)
                    .font(.headline)
                if let area = candidate.area {
                    Text(area)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            if isSelected {
                Button(
                    isMustGo ? "Remove must-go" : "Mark must-go",
                    systemImage: isMustGo ? "star.fill" : "star",
                    action: onToggleMustGo
                )
                .labelStyle(.iconOnly)
                .foregroundStyle(isMustGo ? .orange : .secondary)
                .frame(minWidth: AppLayout.minimumTapHeight, minHeight: AppLayout.minimumTapHeight)
            }

            Button(
                isSelected ? "Remove from shortlist" : "Add to shortlist",
                systemImage: isSelected ? "minus.circle" : "plus.circle",
                action: onToggleSelection
            )
            .labelStyle(.iconOnly)
            .frame(minWidth: AppLayout.minimumTapHeight, minHeight: AppLayout.minimumTapHeight)
        }
    }
}
