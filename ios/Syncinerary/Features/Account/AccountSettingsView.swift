import SwiftUI

struct AccountSettingsView: View {
    @Environment(AccountStore.self) private var accounts
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("AI") {
                    NavigationLink("AI privacy") {
                        AnthropicConsentView()
                    }
                    NavigationLink("Anthropic API key") {
                        AnthropicCredentialView()
                    }
                }

                Section("Help and legal") {
                    if let privacyPolicy = LegalLinks.privacyPolicy {
                        Link("Privacy policy", destination: privacyPolicy)
                    }
                    if let support = LegalLinks.support {
                        Link("Support", destination: support)
                    }
                }

                Section("Account") {
                    Button("Sign out") {
                        Task {
                            await accounts.signOut()
                            if !accounts.isSignedIn { dismiss() }
                        }
                    }
                    .disabled(accounts.isWorking)

                    NavigationLink("Delete account") {
                        DeleteAccountView()
                    }
                    .foregroundStyle(AppTheme.stamp)
                }
            }
            .navigationTitle("Account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
