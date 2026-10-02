import SwiftUI

/// Shared travel colors and motion. Asset variants keep contrast in both appearances.
enum AppTheme {
    static let canvas = Color("Canvas")
    static let surface = Color("Surface")
    static let paper = Color("Paper")
    static let ink = Color("Ink")
    static let faded = Color("Faded")
    static let rule = Color("Rule")
    static let accent = Color("AccentColor")
    static let onAccent = Color("OnAccent")
    static let highlight = Color("Highlight")
    static let onHighlight = Color("OnHighlight")
    static let stamp = Color("Stamp")
    static let jade = Color("Jade")
    static let violet = Color("Violet")

    /// Darkens the top of a photo so the attribution stays readable.
    static let photoScrim = LinearGradient(
        colors: [.black.opacity(0.55), .clear],
        startPoint: .top,
        endPoint: .bottom
    )

    // MARK: Spacing and shape

    static let spacingXS = 4.0
    static let spacingS = 8.0
    static let spacingM = 12.0
    static let spacingL = 16.0
    static let spacingXL = 24.0

    /// Shared rounding for media and compact surfaces.
    static let cornerRadius = 18.0
    static let hairlineWidth = 1.0

    // MARK: Motion

    /// A card leaving the deck: fast, with a little overshoot.
    static let cardThrow = Animation.spring(duration: 0.38, bounce: 0.15)
    /// A card returning to centre, or the next card settling into place.
    static let settle = Animation.spring(duration: 0.45, bounce: 0.3)
    /// A stamp coming down: quick, and it lands hard.
    static let stampDown = Animation.spring(duration: 0.28, bounce: 0.5)
    /// Cross-fades, and the Reduce Motion fallback everywhere.
    static let fade = Animation.easeInOut(duration: 0.18)
    static let press = Animation.spring(duration: 0.26, bounce: 0.22)
    static let selection = Animation.spring(duration: 0.34, bounce: 0.18)

    /// transitions.dev surface timing for pages, tabs, and disclosures.
    static let surfaceChange = Animation.timingCurve(0.22, 1, 0.36, 1, duration: 0.25)
    static let textSwap = Animation.easeInOut(duration: 0.15)
    static let confirmation = Animation.timingCurve(0.22, 1, 0.36, 1, duration: 0.5)
    static let pageTravel = 8.0
    static let textTravel = 4.0
}
