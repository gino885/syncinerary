import SwiftUI

struct MealBreakRow: View {
    let meal: MealBreak
    @ScaledMetric(relativeTo: .body) private var timeColumnWidth = 56
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: AppTheme.spacingS))
            : AnyLayout(HStackLayout(alignment: .top, spacing: AppTheme.spacingL))
        layout {
            VStack(alignment: .leading, spacing: 2) {
                Text(meal.startTime.prefix(5)).font(AppType.monoBody).bold().foregroundStyle(AppTheme.accent)
                Text(meal.endTime.prefix(5)).font(AppType.mono).foregroundStyle(AppTheme.faded)
            }
            .monospacedDigit()
            .fixedSize(horizontal: true, vertical: false)
            .frame(width: dynamicTypeSize.isAccessibilitySize ? nil : timeColumnWidth, alignment: .leading)
            VStack(alignment: .leading, spacing: AppTheme.spacingS) {
                Text(meal.title).font(AppType.rowTitle)
                Link("Find nearby restaurants", destination: meal.nearbyURL)
                    .font(.subheadline)
                    .underline()
                    .frame(minHeight: AppLayout.minimumTapHeight, alignment: .leading)
            }
        }
        .foregroundStyle(AppTheme.ink)
        .padding(AppTheme.spacingL)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.surface, in: .rect(cornerRadius: 20))
    }
}
