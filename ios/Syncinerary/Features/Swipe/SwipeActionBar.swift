import SwiftUI

/// The three vote buttons from CLAUDE.md 9.2. Long-pressing Like is the
/// must-have shortcut, mirrored by an upward swipe on the card.
struct SwipeActionBar: View {
    let isDisabled: Bool
    let onDislike: () -> Void
    let onLikeWithNote: () -> Void
    let onLike: () -> Void
    let onMustHave: () -> Void

    @State private var didLongPressLike = false

    var body: some View {
        HStack(spacing: AppTheme.spacingXL) {
            RoundActionButton(title: "Pass", systemImage: "xmark", ink: AppTheme.faded, action: onDislike)

            RoundActionButton(title: "Like with a note", systemImage: "square.and.pencil", ink: AppTheme.ink, action: onLikeWithNote)

            RoundActionButton(title: "Like", systemImage: "checkmark", ink: AppTheme.stamp, isProminent: true, action: like)
                .simultaneousGesture(
                    LongPressGesture(minimumDuration: 0.6)
                        .onEnded { _ in
                            didLongPressLike = true
                            onMustHave()
                        }
                )
                .accessibilityHint("Double tap to like. Long press to mark as must go.")
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

#Preview {
    SwipeActionBar(isDisabled: false, onDislike: { }, onLikeWithNote: { }, onLike: { }, onMustHave: { })
        .padding()
        .background(AppTheme.paper)
}
