import SwiftUI

/// Where the group's decision stands, written out rather than tallied in
/// boxes: the numbers matter, so they are set in the display serif and the
/// confirmation carries a stamp once it is met.
struct ShortlistTallyLine: View {
    let goingCount: Int
    let mustGoCount: Int
    let mustGoLimit: Int
    let confirmed: Int
    let required: Int

    private var isConfirmed: Bool {
        required > 0 && confirmed >= required
    }

    var body: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
                Text("\(goingCount) places going")
                    .font(AppType.name)
                    .foregroundStyle(AppTheme.ink)
                MetaLabel("\(mustGoCount) of \(mustGoLimit) must-go · \(confirmed) of \(required) confirmed")
            }
            Spacer(minLength: AppTheme.spacingM)
            if isConfirmed {
                StampView(mark: .confirmed, scale: 0.7, isDecorative: false)
            }
        }
        .padding(.vertical, AppTheme.spacingM)
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    ShortlistTallyLine(goingCount: 14, mustGoCount: 2, mustGoLimit: 5, confirmed: 2, required: 2)
        .padding()
        .background(AppTheme.paper)
}
