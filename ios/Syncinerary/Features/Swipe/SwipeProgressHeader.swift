import SwiftUI

/// How far through the deck, as a ruled line rather than a bar.
struct SwipeProgressHeader: View {
    let current: Int
    let total: Int
    let progressText: String
    let canGoBack: Bool
    let onPrevious: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            HStack(spacing: AppTheme.spacingM) {
                MetaLabel(progressText, color: AppTheme.ink)
                Spacer(minLength: 0)
                Button("Previous", systemImage: "arrow.uturn.backward", action: onPrevious)
                    .font(.subheadline)
                    .foregroundStyle(canGoBack ? AppTheme.ink : AppTheme.faded)
                    .frame(minHeight: AppLayout.minimumTapHeight)
                    .disabled(!canGoBack)
            }
            ProgressView(value: Double(current), total: Double(max(total, 1)))
                .tint(AppTheme.stamp)
                .accessibilityLabel("Swipe progress")
                .accessibilityValue(progressText)
        }
    }
}

#Preview {
    SwipeProgressHeader(
        current: 11,
        total: 40,
        progressText: "Card 12 of 40",
        canGoBack: true,
        onPrevious: { }
    )
        .padding()
        .background(AppTheme.paper)
}
