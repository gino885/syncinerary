import SwiftUI

/// How far through the deck, as a ruled line rather than a bar.
struct SwipeProgressHeader: View {
    let current: Int
    let total: Int
    let progressText: String

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            MetaLabel(progressText, color: AppTheme.ink)
            ProgressView(value: Double(current), total: Double(max(total, 1)))
                .tint(AppTheme.stamp)
                .accessibilityLabel("Swipe progress")
                .accessibilityValue(progressText)
        }
    }
}

#Preview {
    SwipeProgressHeader(current: 11, total: 40, progressText: "Card 12 of 40")
        .padding()
        .background(AppTheme.paper)
}
