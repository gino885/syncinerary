import SwiftUI

/// A short shower of emoji over the deck after a decision. Decorative only:
/// it never takes touches and is hidden from VoiceOver.
struct EmojiBurstView: View {
    let particles: [EmojiParticle]

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            ForEach(particles) { particle in
                EmojiParticleView(particle: particle, reduceMotion: reduceMotion)
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

#Preview {
    EmojiBurstView(particles: EmojiParticle.burst(["❤️", "🥰", "✨", "🍜"]))
        .frame(maxWidth: .infinity, maxHeight: .infinity)
}
