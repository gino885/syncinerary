import SwiftUI

/// Pops in, then floats up and fades. With Reduce Motion it only fades.
struct EmojiParticleView: View {
    let particle: EmojiParticle
    let reduceMotion: Bool

    @State private var popped = false
    @State private var flew = false

    var body: some View {
        Text(particle.emoji)
            .font(.largeTitle)
            .scaleEffect(popped ? particle.scale : 0.4)
            .rotationEffect(.degrees(flew && !reduceMotion ? particle.rotation : 0))
            .offset(
                x: reduceMotion ? 0 : particle.spread * (flew ? 130 : 30),
                y: reduceMotion ? 0 : (flew ? -particle.rise : 0)
            )
            .opacity(flew ? 0 : 1)
            .onAppear(perform: launch)
    }

    private func launch() {
        withAnimation(AppTheme.stampDown.delay(particle.delay)) {
            popped = true
        } completion: {
            withAnimation(.easeOut(duration: reduceMotion ? 0.6 : 1.0)) {
                flew = true
            }
        }
    }
}
