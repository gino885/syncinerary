import SwiftUI

struct ItineraryStopRow: View {
    let stop: ItineraryStop

    var body: some View {
        VStack(alignment: .leading) {
            LabeledContent(stop.name, value: stop.timeRange)
                .bold()

            if let area = stop.area {
                Label(area, systemImage: "mappin")
                    .foregroundStyle(.secondary)
            }

            if stop.transitFromPrevMin > 0 {
                Label(
                    "^[\(stop.transitFromPrevMin) minute](inflect: true) by \(stop.transitLabel)",
                    systemImage: "figure.walk"
                )
                .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}
