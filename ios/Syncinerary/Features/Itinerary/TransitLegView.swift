import SwiftUI

/// "12 MIN WALK" between two stops.
struct TransitLegView: View {
    let minutes: Int
    let mode: String?

    var body: some View {
        MetaLabel("\(minutes) min \(modeLabel)")
            .accessibilityLabel("\(minutes) minutes \(modeLabel)")
    }

    private var modeLabel: String {
        switch mode {
        case "walk": "walk"
        case "taxi": "taxi"
        case let value? where value.hasPrefix("transit"): "transit"
        default: "travel"
        }
    }
}

#Preview {
    VStack(alignment: .leading) {
        TransitLegView(minutes: 12, mode: "walk")
        TransitLegView(minutes: 25, mode: "transit_transitous")
    }
    .padding()
}
