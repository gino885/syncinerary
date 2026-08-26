import SwiftUI

struct SwipeControls: View {
    let isDisabled: Bool
    let onDislike: () -> Void
    let onLike: () -> Void

    var body: some View {
        HStack {
            Button("Dislike", systemImage: "hand.thumbsdown", action: onDislike)
                .buttonStyle(.bordered)
                .frame(maxWidth: .infinity, minHeight: AppLayout.minimumTapHeight)

            Button("Like", systemImage: "hand.thumbsup", action: onLike)
                .buttonStyle(.borderedProminent)
                .frame(maxWidth: .infinity, minHeight: AppLayout.minimumTapHeight)
        }
        .disabled(isDisabled)
    }
}
