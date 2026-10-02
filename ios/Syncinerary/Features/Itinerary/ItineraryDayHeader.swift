import SwiftUI

struct ItineraryDayHeader: View {
    let day: ItineraryDay
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 16))
            : AnyLayout(HStackLayout(alignment: .center, spacing: 16))
        layout {
            DayMarker(day: day.day)
            VStack(alignment: .leading, spacing: 4) {
                Text(dateText).font(AppType.dayDate).foregroundStyle(AppTheme.ink)
                MetaLabel("\(day.stops.count) stops")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, AppTheme.spacingL)
        .padding(.bottom, AppTheme.spacingS)
        .textCase(nil)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }

    private var dateText: String {
        guard let date = TripDate.parse(day.date) else { return day.date }
        return date.formatted(TripDate.weekday)
    }
}
