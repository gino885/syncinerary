import SwiftUI

/// The end of the deck: the page gets stamped.
struct VotingCompleteView: View {
    let onContinue: () -> Void
    let onReviewLast: () -> Void

    @State private var isStamped = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingL) {
            EyebrowText("Votes in")

            Text("Every card swiped.")
                .font(AppType.title)
                .foregroundStyle(AppTheme.ink)

            StampView(mark: .confirmed, scale: 1.2)
                .scaleEffect(isStamped ? 1 : (reduceMotion ? 1 : 2.4))
                .opacity(isStamped ? 1 : 0)
                .padding(.vertical, AppTheme.spacingM)

            Text("Now see what the group agreed on.")
                .foregroundStyle(AppTheme.faded)

            Button("See the shortlist", action: onContinue)
                .buttonStyle(.stamp)
                .padding(.top, AppTheme.spacingS)

            Button("Review last card", systemImage: "arrow.uturn.backward", action: onReviewLast)
                .foregroundStyle(AppTheme.ink)
                .frame(minHeight: AppLayout.minimumTapHeight)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(AppTheme.spacingXL)
        .background(AppTheme.paper)
        .task {
            withAnimation(reduceMotion ? AppTheme.fade : AppTheme.stampDown) {
                isStamped = true
            }
        }
    }
}

#Preview {
    VotingCompleteView(onContinue: { }, onReviewLast: { })
}
