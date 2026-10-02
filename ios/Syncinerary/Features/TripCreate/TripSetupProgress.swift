import SwiftUI

struct TripSetupProgress: View {
    let step: Int
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 6) {
                ForEach(0..<3) { index in
                    Capsule()
                        .fill(index <= step ? AppTheme.accent : AppTheme.rule)
                        .frame(height: index == step ? 6 : 3)
                }
                Text("\(step + 1) / 3")
                    .font(.caption.monospacedDigit())
                    .fixedSize()
                    .foregroundStyle(AppTheme.faded)
                    .padding(.leading, 12)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Step \(step + 1) of 3")
            Text(title)
                .font(.system(dynamicTypeSize.isAccessibilitySize ? .title2 : .largeTitle, design: .rounded, weight: .bold))
                .contentTransition(.opacity)
                .accessibilityAddTraits(.isHeader)
        }
        .padding(.bottom, 8)
        .animation(reduceMotion ? AppTheme.fade : .smooth(duration: 0.35), value: step)
    }

    private var title: LocalizedStringKey {
        switch step {
        case 0: "A place to begin."
        case 1: "Make it yours."
        default: "Find your rhythm."
        }
    }
}
