import SwiftUI

struct RoundActionButton: View {
    let title: LocalizedStringKey
    let systemImage: String
    var ink: Color = AppTheme.ink
    var isProminent = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .labelStyle(.iconOnly)
                .font(isProminent ? .title : .title3)
                .foregroundStyle(isProminent ? AppTheme.canvas : ink)
                .frame(width: isProminent ? 72 : 56, height: isProminent ? 72 : 56)
                .background(isProminent ? ink : AppTheme.surface, in: .circle)
                .contentShape(.circle)
        }
        .buttonStyle(PressFeedbackStyle())
    }
}
