import SwiftUI

/// The trip journal (UIUX_PLAN.md section 9): indigo ink on stone paper,
/// with three stamp inks for the three kinds of approval this app deals in.
/// Every screen draws from these tokens; nothing declares a colour of its own.
enum AppTheme {
    // MARK: Colours (asset catalog, light and dark)

    /// The ground: a stone paper with a green-grey cast, not warm cream.
    static let paper = Color("Paper")
    /// Text: an indigo pen rather than black.
    static let ink = Color("Ink")
    /// Secondary text, the way older pencil goes grey.
    static let faded = Color("Faded")
    /// Ledger hairlines. Only where a rule means a boundary.
    static let rule = Color("Rule")

    /// Stamp inks. A passport page carries several, and so does this app:
    /// vermilion for a like, jade for something settled, violet for must-go.
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

    /// Photos and the primary button. Stamps and rules stay square.
    static let cornerRadius = 6.0
    static let hairlineWidth = 1.0

    // MARK: Motion

    /// A card leaving the deck: fast, with a little overshoot.
    static let cardThrow = Animation.spring(duration: 0.38, bounce: 0.15)
    /// A card returning to centre, or the next card settling into place.
    static let settle = Animation.spring(duration: 0.45, bounce: 0.3)
    /// A stamp coming down: quick, and it lands hard.
    static let stampDown = Animation.spring(duration: 0.28, bounce: 0.5)
    /// Cross-fades, and the Reduce Motion fallback everywhere.
    static let fade = Animation.easeInOut(duration: 0.35)
}
