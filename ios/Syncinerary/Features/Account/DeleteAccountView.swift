import SwiftUI

struct DeleteAccountView: View {
    @Environment(AccountStore.self) private var accounts
    @Environment(\.dismiss) private var dismiss
    @State private var currentPassword = ""
    @State private var confirmation = ""
    @State private var isConfirming = false
    @State private var socialWorking = false
    @State private var socialIdentity: SocialSignInRequest?
    private var provider: String { accounts.account?.authProvider ?? "email" }

    private var canDelete: Bool {
        (provider == "email"
            ? (8...128).contains(currentPassword.unicodeScalars.count)
            : socialIdentity != nil)
            && confirmation == "DELETE"
            && !accounts.isWorking
            && !socialWorking
    }

    var body: some View {
        Form {
            Section {
                Text("This permanently deletes your account, encrypted Anthropic key, sessions, trips you created, and your messages, votes, preferences, and saved links in trips you joined. Friends will lose access to trips you created.")
            }

            Section("Confirm your identity") {
                if provider == "email" {
                    SecureField("Current password", text: $currentPassword)
                        .textContentType(.password)
                        .privacySensitive()
                } else {
                    SocialSignInButtons(isWorking: $socialWorking, isDisabled: accounts.isWorking,
                                        onlyProvider: provider) { _, identity in
                        socialIdentity = identity
                        return true
                    }
                    if socialIdentity != nil { Text("Identity ready to confirm. Continue within five minutes.").font(.footnote) }
                }
                TextField("Type DELETE", text: $confirmation)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
            }

            Section {
                Button("Delete account", role: .destructive) {
                    isConfirming = true
                }
                .disabled(!canDelete)
            }

            if let error = accounts.errorMessage {
                Section {
                    Text(error)
                        .foregroundStyle(AppTheme.stamp)
                        .accessibilityLabel("Error: \(error)")
                }
            }
        }
        .navigationTitle("Delete account")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(
            "Delete this account permanently?",
            isPresented: $isConfirming,
            titleVisibility: .visible
        ) {
            Button("Delete permanently", role: .destructive) {
                Task {
                    if await accounts.deleteAccount(currentPassword: provider == "email" ? currentPassword : nil,
                                                    socialIdentity: socialIdentity) {
                        currentPassword = ""
                        confirmation = ""
                        dismiss()
                    }
                    socialIdentity = nil
                }
            }
        } message: {
            Text("This cannot be undone.")
        }
        .onDisappear { currentPassword = ""; socialIdentity = nil }
    }
}
