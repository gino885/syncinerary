import SwiftUI

struct MealBreakRow: View {
    let meal: MealBreak
    @ScaledMetric(relativeTo: .body) private var timeColumnWidth = 56

    var body: some View {
        HStack(alignment: .top, spacing: AppTheme.spacingL) {
            VStack(alignment: .leading, spacing: 2) {
                Text(meal.startTime.prefix(5)).font(AppType.monoBody).bold()
                Text(meal.endTime.prefix(5)).font(AppType.mono).foregroundStyle(AppTheme.faded)
            }
            .monospacedDigit()
            .frame(width: timeColumnWidth, alignment: .leading)
            VStack(alignment: .leading, spacing: AppTheme.spacingS) {
                Text(meal.title).font(AppType.rowTitle)
                Link("Find nearby restaurants", destination: meal.nearbyURL)
                    .font(.subheadline)
                    .underline()
                    .frame(minHeight: AppLayout.minimumTapHeight, alignment: .leading)
            }
        }
        .foregroundStyle(AppTheme.ink)
        .padding(.vertical, AppTheme.spacingS)
    }
}
