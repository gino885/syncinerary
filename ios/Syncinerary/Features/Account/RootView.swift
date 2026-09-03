import SwiftUI

/// Signed out shows the cover; signed in shows the board.
///
/// The exception that matters: an invite link goes straight to the trip
/// preview, signed in or not. Making an invited person sign in before they can
/// see what they were invited to is the friction every comparison of these
/// apps names as the thing that kills group adoption.
struct RootView: View {
    @Environment(AccountStore.self) private var accounts

    @State private var hasRestored = false
    @State private var pendingInvite: String?

    var body: some View {
        Group {
            if let pendingInvite, !accounts.isSignedIn {
                NavigationStack {
                    InvitePreviewView(code: pendingInvite) {
                        // Identity last: the decision is made, now ask who.
                        self.acceptedInvite = pendingInvite
                        self.pendingInvite = nil
                    }
                }
            } else if accounts.isSignedIn {
                ContentView(openingInvite: acceptedInvite ?? pendingInvite)
            } else {
                SignInView(invitedTo: acceptedInvite)
            }
        }
        .tint(AppTheme.ink)
        .task {
            guard !hasRestored else { return }
            hasRestored = true
            // Development only, matching SYNC_RESUME_TRIP_ID: opens the invite
            // preview without the system's "Open in?" confirmation, which
            // cannot be dismissed from a script.
            if let seeded = UserDefaults.standard.string(forKey: "SYNC_INVITE_CODE"),
               !seeded.isEmpty {
                pendingInvite = seeded.uppercased()
            }
            await accounts.restore()
        }
        .onOpenURL { url in
            guard let code = InviteLink.code(from: url) else { return }
            pendingInvite = code
        }
    }

    @State private var acceptedInvite: String?
}
