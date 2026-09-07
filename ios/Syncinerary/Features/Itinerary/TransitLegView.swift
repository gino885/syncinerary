import SwiftUI

/// "12 MIN WALK" between two stops.
struct TransitLegView: View {
    let minutes: Int
    let mode: String?

    var body: some View {
        MetaLabel("\(minutes) min \(modeLabel)")
            .accessibilityLabel("\(minutes) minutes \(modeLabel)")
    }

    /// An estimated leg says so.
    ///
    /// The solver fills a gap in the provider's coverage with a distance
    /// estimate so a day is not silently torn apart, but a number nobody
    /// routed must not be shown as one that was. Same rule as the source
    /// badges: never present what was not measured as though it were.
    private var modeLabel: String {
        guard let mode else { return "travel" }
        let base: String =
            switch mode {
            case "walk", "walking", "walking_estimated": "walk"
            case "taxi": "taxi"
            case let value where value.hasPrefix("transit"): "transit"
            default: "travel"
            }
        return mode.hasSuffix("_estimated") ? "approx. \(base)" : base
    }
}

#Preview {
    VStack(alignment: .leading) {
        TransitLegView(minutes: 12, mode: "walk")
        TransitLegView(minutes: 25, mode: "transit_transitous")
        TransitLegView(minutes: 34, mode: "transit_estimated")
    }
    .padding()
}
