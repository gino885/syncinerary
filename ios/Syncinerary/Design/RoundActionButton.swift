import SwiftUI

/// The circular buttons under the deck: ink outlines on paper, with the
/// like button filled in stamp ink so one thing on the screen is loud.
struct RoundActionButton: View {
    let title: String
    let systemImage: String
    var ink: Color = AppTheme.ink
    var isProminent = false
    let action: () -> Void

    private var diameter: Double {
        isProminent ? 70 : 56
    }

    var body: some View {
        Button(title, systemImage: systemImage, action: action)
            .labelStyle(.iconOnly)
            .font(isProminent ? .title : .title3)
            .foregroundStyle(isProminent ? AppTheme.paper : ink)
            .frame(width: diameter, height: diameter)
            .background(isProminent ? ink : .clear, in: .circle)
            .overlay {
                Circle().stroke(ink, lineWidth: isProminent ? 0 : 1.5)
            }
            .contentShape(.circle)
    }
}

#Preview {
    HStack(spacing: 28) {
        RoundActionButton(title: "Pass", systemImage: "xmark", ink: AppTheme.faded, action: { })
        RoundActionButton(title: "Note", systemImage: "square.and.pencil", action: { })
        RoundActionButton(title: "Like", systemImage: "checkmark", ink: AppTheme.stamp, isProminent: true, action: { })
    }
    .padding(40)
    .background(AppTheme.paper)
}
