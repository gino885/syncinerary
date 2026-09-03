import SwiftUI

/// The journal's inside cover, where you write your name.
///
/// Two ruled lines and nothing else: no card, no explanatory sentence. The
/// placeholders are the explanation (ios-design-taste section 5).
struct SignInView: View {
    @Environment(AccountStore.self) private var accounts

    /// Set when they arrived from an invite: the screen then says what
    /// they are joining rather than asking for a handle out of nowhere.
    var invitedTo: String?

    @State private var displayName = ""
    @State private var handle = ""
    @FocusState private var focus: Field?

    private enum Field { case name, handle }

    private var canContinue: Bool {
        !displayName.trimmingCharacters(in: .whitespaces).isEmpty
            && handle.trimmingCharacters(in: .whitespaces).count >= 3
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingXL) {
            VStack(alignment: .leading, spacing: AppTheme.spacingS) {
                if invitedTo != nil {
                    EyebrowText("One more thing")
                }
                Text(invitedTo == nil ? "Syncinerary" : "Who are you?")
                    .font(AppType.title)
                    .foregroundStyle(AppTheme.ink)
            }

            VStack(alignment: .leading, spacing: AppTheme.spacingXL) {
                ruledField(
                    "Your name",
                    text: $displayName,
                    field: .name,
                    mono: false
                )
                .textInputAutocapitalization(.words)

                ruledField(
                    "@handle",
                    text: $handle,
                    field: .handle,
                    mono: true
                )
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            }

            if let message = accounts.errorMessage {
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(AppTheme.stamp)
            }

            // Ink, not the vermilion stamp. The token plan spends no accent
            // on this screen, and a disabled accent button reads as pale coral
            // on this ground, which is the look the whole system avoids.
            Button("Continue") {
                Task { await accounts.signIn(displayName: displayName, handle: handle) }
            }
            .buttonStyle(StampButtonStyle(ink: AppTheme.ink))
            .disabled(!canContinue || accounts.isWorking)
            .padding(.top, AppTheme.spacingM)

            Spacer()
        }
        .padding(AppTheme.spacingL)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.paper)
        .onAppear { focus = .name }
    }

    private func ruledField(
        _ placeholder: String,
        text: Binding<String>,
        field: Field,
        mono: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            TextField(placeholder, text: text)
                .font(mono ? AppType.monoBody : AppType.body)
                .foregroundStyle(AppTheme.ink)
                .focused($focus, equals: field)
                .submitLabel(field == .name ? .next : .go)
                .onSubmit {
                    if field == .name {
                        focus = .handle
                    } else if canContinue {
                        Task {
                            await accounts.signIn(
                                displayName: displayName,
                                handle: handle
                            )
                        }
                    }
                }
            Rectangle()
                .fill(focus == field ? AppTheme.ink : AppTheme.rule)
                .frame(height: AppTheme.hairlineWidth)
        }
    }
}
