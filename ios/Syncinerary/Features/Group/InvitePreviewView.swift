import SwiftUI

/// What an invited person sees before they are asked who they are.
///
/// Partiful's finding, and the reason it grew the way it did: people hesitate
/// to commit when they cannot tell what they are walking into. So the trip and
/// the people already in it come first, and identity comes after the decision.
struct InvitePreviewView: View {
    let code: String
    let onJoin: () -> Void

    @State private var preview: InvitePreview?
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingXL) {
            if let preview {
                VStack(alignment: .leading, spacing: AppTheme.spacingS) {
                    EyebrowText("You're invited to")
                    Text(preview.trip.destination)
                        .font(AppType.title)
                        .foregroundStyle(AppTheme.ink)
                    Text(
                        "\(TripDate.range(preview.trip.startDate, preview.trip.endDate))"
                        + " · \(preview.trip.days) days"
                    )
                        .font(AppType.mono)
                        .monospacedDigit()
                        .foregroundStyle(AppTheme.faded)
                }

                if !preview.memberNames.isEmpty {
                    VStack(alignment: .leading, spacing: AppTheme.spacingS) {
                        EyebrowText("Already in")
                        Text(preview.memberNames.joined(separator: ", "))
                            .font(AppType.body)
                            .foregroundStyle(AppTheme.ink)
                    }
                }

                if preview.usable {
                    Button("Join trip", action: onJoin)
                        .buttonStyle(StampButtonStyle(ink: AppTheme.ink))
                } else if let reason = preview.reason {
                    Text(reason)
                        .font(AppType.body)
                        .foregroundStyle(AppTheme.stamp)
                }
            } else if let errorMessage {
                Text(errorMessage)
                    .font(AppType.body)
                    .foregroundStyle(AppTheme.stamp)
            } else {
                ProgressView().tint(AppTheme.faded)
            }

            Spacer()
        }
        .padding(AppTheme.spacingL)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.paper)
        .task { await load() }
    }

    private func load() async {
        do {
            preview = try await APIClient.shared.invitePreview(code: code)
        } catch {
            errorMessage = "That invite code doesn't match a trip. Ask for a new one."
        }
    }
}
