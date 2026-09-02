import SwiftUI

/// The end of the deck: the page gets stamped.
struct VotingCompleteView: View {
    let onContinue: () -> Void

    @State private var burst: [EmojiParticle] = []
    @State private var isStamped = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
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
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(AppTheme.spacingXL)

            EmojiBurstView(particles: burst)
        }
        .background(AppTheme.paper)
        .task {
            burst = EmojiParticle.burst(["🎉", "✨", "🧳", "🗺️", "🍜", "📸"], count: 14)
            withAnimation(reduceMotion ? AppTheme.fade : AppTheme.stampDown) {
                isStamped = true
            }
        }
    }
}

#Preview {
    VotingCompleteView(onContinue: { })
}
