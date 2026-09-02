import SwiftUI

struct ItineraryDaySection: View {
    let day: ItineraryDay

    var body: some View {
        Section {
            if day.stops.isEmpty {
                Text("Nothing scheduled")
                    .foregroundStyle(AppTheme.faded)
            } else {
                ForEach(day.stops) { stop in
                    ItineraryStopRow(stop: stop)
                }
            }
        } header: {
            ItineraryDayHeader(day: day)
        }
        .journalRow()
    }
}
