import SwiftUI

struct ItineraryDaySection: View {
    let day: ItineraryDay
    var onAdd: (() -> Void)? = nil
    var onEdit: ((ItineraryStop) -> Void)? = nil

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
                    case .stop(let stop):
                        ItineraryStopRow(stop: stop)
                            .listRowSeparator(.hidden)
                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                if let onEdit { Button("Edit", systemImage: "pencil") { onEdit(stop) } }
                            }
                            .contextMenu {
                                if let onEdit { Button("Edit stop", systemImage: "pencil") { onEdit(stop) } }
                            }
                    case .meal(let meal): MealBreakRow(meal: meal).listRowSeparator(.hidden)
                    }
                }
            }
            if let onAdd {
                Button("Add a place", systemImage: "plus.circle.fill", action: onAdd)
                    .font(.headline)
                    .foregroundStyle(AppTheme.accent)
                    .frame(minHeight: 48)
                    .listRowSeparator(.hidden)
            }
        } header: {
            ItineraryDayHeader(day: day)
        }
        .journalRow()
    }
}
