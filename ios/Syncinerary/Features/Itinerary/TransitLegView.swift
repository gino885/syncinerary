import SwiftUI

/// "12 MIN WALK" between two stops.
struct TransitLegView: View {
    let minutes: Int
    let mode: String?

    var body: some View {
        MetaLabel("\(minutes) min \(modeLabel)")
            .accessibilityLabel("\(minutes) minutes \(modeLabel)")
    }

    /// An estimated leg says so, and nothing else does.
    ///
    /// The backend tries several transit providers before giving up on a
    /// pair and filling the gap with a distance estimate, so a day is not
    /// silently torn apart. Which provider answered is internal: a leg is
    /// either routed or approximate here, because that is the only part of
    /// it a traveler can act on. Same rule as the source badges: never
    /// present what was not measured as though it were.
    private var modeLabel: String {
        guard let mode else { return String(localized: "travel") }
        let base: String =
            switch mode {
            case "walk", "walking", "walking_estimated": String(localized: "walk")
            case "taxi": String(localized: "taxi")
            case let value where value.hasPrefix("transit"): String(localized: "transit")
            default: String(localized: "travel")
            }
        // The approximate marker wraps the mode rather than being appended, so
        // a language that puts the qualifier elsewhere can move it.
        return mode.hasSuffix("_estimated")
            ? String(localized: "approx. \(base)")
            : base
    }
}

#Preview {
    VStack(alignment: .leading) {
        TransitLegView(minutes: 12, mode: "walk")
        TransitLegView(minutes: 25, mode: "transit")
        TransitLegView(minutes: 34, mode: "transit_estimated")
    }
    .padding()
}
