import SwiftUI

/// Signed out shows the cover; signed in shows the board.
///
/// The single-trip resume this replaced assumed one obvious trip to reopen,
/// which stops being true the moment someone is on two.
struct RootView: View {
    @Environment(AccountStore.self) private var accounts

    @State private var hasRestored = false

    var body: some View {
        Group {
            if accounts.isSignedIn {
                ContentView()
            } else {
                SignInView()
            }
        }
        .tint(AppTheme.ink)
        .task {
            guard !hasRestored else { return }
            hasRestored = true
            await accounts.restore()
        }
    }
}
