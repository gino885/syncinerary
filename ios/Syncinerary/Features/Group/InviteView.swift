import SwiftUI

/// The code is the whole screen.
///
/// The only centred screen in the app, which section 4 of ios-design-taste
/// allows for a single object that stands alone. Set as a boarding-pass
/// reference: cities above in condensed caps, the code below in tracked
/// monospace.
struct InviteView: View {
    let trip: TripListRow

    @State private var invite: TripInvite?
    @State private var errorMessage: String?
    @State private var isWorking = false

    var body: some View {
        VStack(spacing: AppTheme.spacingXL) {
            Spacer()

            Text(trip.destination)
                .font(.system(.title3).width(.condensed).weight(.semibold))
                .textCase(.uppercase)
                .tracking(3)
                .foregroundStyle(AppTheme.faded)
                .multilineTextAlignment(.center)

            if let invite {
                Text(invite.code)
                    .font(.system(size: 44, weight: .semibold, design: .monospaced))
                    .tracking(6)
                    .monospacedDigit()
                    .foregroundStyle(AppTheme.ink)
                    .textSelection(.enabled)
                    .accessibilityLabel(spelledOut(invite.code))

                Text(usesLine(invite))
                    .font(AppType.mono)
                    .foregroundStyle(AppTheme.faded)

                ShareLink(item: shareText(invite)) {
                    Text("Share code")
                }
                .buttonStyle(StampButtonStyle())
            } else if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(AppTheme.stamp)
                    .multilineTextAlignment(.center)
            } else {
                ProgressView().tint(AppTheme.faded)
            }

            Spacer()
        }
        .padding(AppTheme.spacingXL)
        .frame(maxWidth: .infinity)
        .background(AppTheme.paper)
        .task { await create() }
    }

    private func create() async {
        guard invite == nil, !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            // An existing usable code is reused rather than minting a new one
            // per visit, so the group does not end up with a pile of live
            // codes nobody can account for.
            let existing = try await APIClient.shared.invites(tripID: trip.id)
            if let usable = existing.first(where: { !$0.revoked && $0.usesRemaining > 0 }) {
                invite = usable
            } else {
                invite = try await APIClient.shared.createInvite(tripID: trip.id)
            }
        } catch {
            errorMessage = "Could not make an invite code. Try again."
        }
    }

    private func usesLine(_ invite: TripInvite) -> String {
        "\(invite.usesRemaining) of \(invite.maxUses) left"
    }

    private func shareText(_ invite: TripInvite) -> String {
        "Join my \(trip.destination) trip on Syncinerary with code \(invite.code)"
    }

    /// A code read by VoiceOver has to be spelled, or it is heard as a word.
    private func spelledOut(_ code: String) -> String {
        code.map(String.init).joined(separator: " ")
    }
}
