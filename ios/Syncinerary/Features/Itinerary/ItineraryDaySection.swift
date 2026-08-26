import SwiftUI

struct ItineraryDaySection: View {
    let day: ItineraryDay

    var body: some View {
        Section("Day \(day.day + 1), \(day.date)") {
            if day.stops.isEmpty {
                Text("No stops scheduled")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(day.stops) { stop in
                    ItineraryStopRow(stop: stop)
                }
            }
        }
    }
}
