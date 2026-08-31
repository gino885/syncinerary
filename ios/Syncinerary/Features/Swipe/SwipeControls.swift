import SwiftUI

struct SwipeControls: View {
    let isDisabled: Bool
    let onDislike: () -> Void
    let onLike: () -> Void
    let onLikeWithNote: () -> Void
    let onMustHave: () -> Void

    @State private var didLongPressLike = false

    var body: some View {
        HStack {
            Button("Dislike", systemImage: "hand.thumbsdown", action: onDislike)
                .buttonStyle(.bordered)
                .frame(maxWidth: .infinity, minHeight: AppLayout.minimumTapHeight)

            Button("Add note", systemImage: "note.text.badge.plus", action: onLikeWithNote)
                .buttonStyle(.bordered)
                .frame(maxWidth: .infinity, minHeight: AppLayout.minimumTapHeight)

            Button("Like", systemImage: "hand.thumbsup", action: like)
                .buttonStyle(.borderedProminent)
                .frame(maxWidth: .infinity, minHeight: AppLayout.minimumTapHeight)
                .simultaneousGesture(
                    LongPressGesture(minimumDuration: 0.6)
                        .onEnded { _ in
                            didLongPressLike = true
                            onMustHave()
                        }
                )
                .accessibilityHint("Double tap to like. Long press to mark as must-have.")
        }
        .disabled(isDisabled)
    }

    private func like() {
        if didLongPressLike {
            didLongPressLike = false
        } else {
            onLike()
        }
    }
}
