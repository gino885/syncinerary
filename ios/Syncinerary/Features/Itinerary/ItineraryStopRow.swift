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

            if let description = stop.description {
                Text(description)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if let source = stop.descriptionSource {
                Label("From \(source)", systemImage: "sparkles")
                    .font(.footnote)
                    .foregroundStyle(.blue)
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
