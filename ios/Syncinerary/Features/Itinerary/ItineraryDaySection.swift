import SwiftUI

struct ItineraryDaySection: View {
    let day: ItineraryDay

    private var timeline: [ItineraryTimelineEntry] {
        (day.stops.map(ItineraryTimelineEntry.stop)
         + (day.mealBreaks ?? []).map(ItineraryTimelineEntry.meal))
        .sorted { $0.startTime < $1.startTime }
    }

    var body: some View {
        Section {
            if timeline.isEmpty {
                Text("Nothing scheduled")
                    .foregroundStyle(AppTheme.faded)
            } else {
                ForEach(timeline) { entry in
                    switch entry {
                    case .stop(let stop): ItineraryStopRow(stop: stop)
                    case .meal(let meal): MealBreakRow(meal: meal)
                    }
                }
            }
        } header: {
            ItineraryDayHeader(day: day)
        }
        .journalRow()
    }
}
