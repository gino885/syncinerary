import SwiftUI

struct AnthropicConsentView: View {
    @State private var model = AnthropicConsentViewModel()
    @State private var isConfirmingRevocation = false

    var body: some View {
        Form {
            Section {
                LabeledContent("Anthropic") {
                    Text(model.status.anthropic ? "Allowed" : "Not allowed")
                        .foregroundStyle(
                            model.status.anthropic ? AppTheme.jade : .secondary
                        )
                }

                if model.status.anthropic {
                    Button("Withdraw permission", role: .destructive) {
                        isConfirmingRevocation = true
                    }
                } else {
                    Button("Allow sharing with Anthropic") {
                        Task { await model.grant() }
                    }
                }
            } header: {
                Text("Permission")
            } footer: {
                Text("Syncinerary sends your trip cities, preferences, dietary needs, saved social links, votes, and trip instructions to Anthropic only to create recommendations and itineraries. Your account email, password, and Anthropic API key are not included. Every member chooses separately.")
            }

            Section("Your control") {
                Text("You can withdraw at any time. New AI steps for your shared trips stop until every member has granted permission again.")
            }

            if let error = model.errorMessage {
                Section {
                    Text(error)
                        .foregroundStyle(AppTheme.stamp)
                        .accessibilityLabel("Error: \(error)")
                }
            }
        }
        .navigationTitle("AI privacy")
        .navigationBarTitleDisplayMode(.inline)
        .disabled(model.isLoading)
        .overlay {
            if model.isLoading {
                ProgressView().accessibilityLabel("Updating AI privacy")
            }
        }
        .task { await model.load() }
        .confirmationDialog(
            "Withdraw Anthropic permission?",
            isPresented: $isConfirmingRevocation,
            titleVisibility: .visible
        ) {
            Button("Withdraw permission", role: .destructive) {
                Task { await model.revoke() }
            }
        } message: {
            Text("New AI work pauses for shared trips that include you.")
        }
    }
}
