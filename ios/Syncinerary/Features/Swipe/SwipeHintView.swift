import SwiftUI

/// One line under the first cards, then gone.
struct SwipeHintView: View {
    var body: some View {
        MetaLabel("← pass · like → · ↑ must go")
            .accessibilityLabel("Swipe left to pass, right to like, up for must go.")
            .transition(.opacity)
    }
}

#Preview {
    SwipeHintView()
        .padding()
        .background(AppTheme.paper)
}
