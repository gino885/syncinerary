import SwiftUI

struct ItineraryDayPicker: View {
    let days: [ItineraryDay]
    @Binding var selection: Int?
    @Namespace private var indicator
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8) {
                tab(title: String(localized: "All days"), value: nil)
                ForEach(days) { day in
                    tab(title: TripDate.parse(day.date)?.formatted(TripDate.short) ?? day.date, value: day.day)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
        }
        .scrollIndicators(.hidden)
        .background(AppTheme.canvas)
        .sensoryFeedback(.selection, trigger: selection)
    }

    private func tab(title: String, value: Int?) -> some View {
        Button {
            withAnimation(reduceMotion ? AppTheme.fade : AppTheme.surfaceChange) { selection = value }
        } label: {
            Text(title)
                .font(.subheadline.bold())
                .foregroundStyle(selection == value ? AppTheme.onAccent : AppTheme.faded)
                .padding(.horizontal, 16)
                .frame(minHeight: 48)
                .fixedSize(horizontal: true, vertical: false)
                .background {
                    if selection == value {
                        if reduceMotion {
                            RoundedRectangle(cornerRadius: 16).fill(AppTheme.accent)
                        } else {
                            RoundedRectangle(cornerRadius: 16).fill(AppTheme.accent)
                                .matchedGeometryEffect(id: "day", in: indicator)
                        }
                    }
                }
                .contentShape(.rect)
        }
        .buttonStyle(PressFeedbackStyle())
        .accessibilityAddTraits(selection == value ? .isSelected : [])
    }
}
