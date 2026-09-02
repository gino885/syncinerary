import SwiftUI

/// What a stamp says and in which ink. The app's states are all approvals of
/// one kind or another, so they all print the same way.
struct StampMark: Hashable, Sendable {
    let text: String
    let ink: Color
    /// Degrees. Stamps are never applied perfectly straight.
    let angle: Double

    static let liked = StampMark(text: "Liked", ink: AppTheme.stamp, angle: -8)
    static let passed = StampMark(text: "Passed", ink: AppTheme.faded, angle: 6)
    static let mustGo = StampMark(text: "★ Must go ★", ink: AppTheme.violet, angle: -5)
    static let noted = StampMark(text: "Noted", ink: AppTheme.stamp, angle: 4)
    static let confirmed = StampMark(text: "Confirmed", ink: AppTheme.jade, angle: -4)

    static func stage(_ text: String, ink: Color) -> StampMark {
        StampMark(text: text, ink: ink, angle: -3)
    }
}
