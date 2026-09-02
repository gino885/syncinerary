import Foundation

/// One emoji in a burst, with the randomness decided once at creation so the
/// view that draws it stays a pure function of this value.
struct EmojiParticle: Identifiable, Hashable, Sendable {
    let id: UUID
    let emoji: String
    /// Horizontal spread, from -1 (far left) to 1 (far right).
    let spread: Double
    /// How far the emoji rises, in points.
    let rise: Double
    /// Final tilt, in degrees.
    let rotation: Double
    /// Final scale relative to the text size.
    let scale: Double
    /// Stagger, in seconds, so a burst does not launch as one block.
    let delay: Double

    static func burst(_ emojis: [String], count: Int = 10) -> [EmojiParticle] {
        guard !emojis.isEmpty else { return [] }
        return (0..<count).map { index in
            EmojiParticle(
                id: UUID(),
                emoji: emojis[index % emojis.count],
                spread: Double.random(in: -1...1),
                rise: Double.random(in: 160...340),
                rotation: Double.random(in: -35...35),
                scale: Double.random(in: 1.0...1.7),
                delay: Double(index) * 0.035
            )
        }
    }
}
