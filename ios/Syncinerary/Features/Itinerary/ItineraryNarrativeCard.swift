import SwiftUI

/// The explainer's story of the trip, folded when it runs long.
struct ItineraryNarrativeCard: View {
    let narrative: String

    @State private var isExpanded = false

    private var isLong: Bool {
        narrative.count > 280
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            EyebrowText("In short")
            Text(narrative)
                .lineLimit(isExpanded || !isLong ? nil : 5)
            if isLong {
                Button(isExpanded ? "Less" : "Read it all", action: toggle)
                    .font(AppType.mono)
                    .textCase(.uppercase)
                    .foregroundStyle(AppTheme.ink)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, AppTheme.spacingL)
        .padding(.vertical, AppTheme.spacingM)
        .animation(AppTheme.fade, value: isExpanded)
    }

    private func toggle() {
        isExpanded.toggle()
    }
}

#Preview {
    ItineraryNarrativeCard(narrative: "Two easy days in Sapporo, then a canal evening in Otaru.")
}
