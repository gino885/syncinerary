import SwiftUI

/// The day, stamped onto the page like an entry mark, with the date and
/// stop count in the margin beside it.
struct ItineraryDayHeader: View {
    let day: ItineraryDay

    var body: some View {
        HStack(alignment: .center, spacing: AppTheme.spacingM) {
            StampView(
                mark: .stage("Day \(day.day + 1)", ink: AppTheme.jade),
                scale: 0.75,
                isDecorative: false
            )
            VStack(alignment: .leading, spacing: 0) {
                Text(dateText)
                    .font(AppType.dayDate)
                    .foregroundStyle(AppTheme.ink)
                MetaLabel("\(day.stops.count) stops")
            }
            Spacer()
        }
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
