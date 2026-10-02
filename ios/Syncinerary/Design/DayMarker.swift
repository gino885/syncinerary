import SwiftUI

/// The trip's actual day number, shared by timetable headings.
struct DayMarker: View {
    let day: Int
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            Text("Day").font(.caption.bold())
            Text(day + 1, format: .number)
                .font(.system(.title, design: .rounded, weight: .heavy))
                .monospacedDigit()
        }
        .foregroundStyle(AppTheme.onHighlight)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(AppTheme.highlight, in: .rect(cornerRadius: 16))
        .rotationEffect(.degrees(reduceMotion ? 0 : -4))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Day \(day + 1)")
    }
}
