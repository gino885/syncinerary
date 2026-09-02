import SwiftUI

/// One small doodle after a decision. It replaces the screen-wide particle
/// shower so the moment stays playful without covering the next card.
struct DecisionCharmView: View {
    let decision: SwipeDecision

    @State private var appeared = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Image(systemName: decision.reactionSymbol)
            .font(.title2)
            .foregroundStyle(decision.stamp.ink)
            .frame(width: 52, height: 52)
            .background(AppTheme.paper, in: .circle)
            .overlay {
                Circle()
                    .stroke(decision.stamp.ink, lineWidth: 1.5)
            }
            .rotationEffect(.degrees(appeared && !reduceMotion ? -8 : 0))
            .scaleEffect(appeared ? 1 : (reduceMotion ? 1 : 0.65))
            .opacity(appeared ? 1 : 0)
            .shadow(color: .black.opacity(0.12), radius: 8, y: 4)
            .onAppear(perform: appear)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }

    private func appear() {
        withAnimation(reduceMotion ? AppTheme.fade : AppTheme.stampDown) {
            appeared = true
        }
    }
}

#Preview {
    DecisionCharmView(decision: .like)
        .padding(60)
        .background(AppTheme.paper)
}
