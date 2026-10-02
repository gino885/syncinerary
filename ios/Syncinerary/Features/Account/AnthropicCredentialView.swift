import SwiftUI

struct AnthropicCredentialView: View {
    @State private var model = AnthropicCredentialViewModel()
    @State private var isConfirmingRemoval = false

    var body: some View {
        Form {
                Section("Status") {
                    LabeledContent("Anthropic API") {
                        if model.status.configured, let suffix = model.status.lastFour {
                            Text("Saved, ending in \(suffix)")
                                .foregroundStyle(AppTheme.jade)
                        } else {
                            Text("No key saved")
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                Section {
                    SecureField("sk-ant-…", text: $model.apiKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .privacySensitive()
                        .accessibilityLabel("Anthropic API key")

                    if let validation = model.validationMessage {
                        Text(validation)
                            .font(.footnote)
                            .foregroundStyle(AppTheme.stamp)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Toggle("Allow AI trip planning", isOn: $model.hasConsent)
                    Text("Allow Syncinerary to send trip cities, preferences, shared links, votes, and instructions to Anthropic to create recommendations and itineraries.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    Button(model.status.configured ? "Replace key" : "Save key") {
                        Task { await model.save() }
                    }
                    .disabled(!model.canSave)
                } header: {
                    Text(model.status.configured ? "Replace key" : "Add key")
                } footer: {
                    Text("Trips you create use your Anthropic account and may incur Anthropic API charges. The key is encrypted on the server and the full value is never shown again.")
                }

                if model.status.configured {
                    Section {
                        Button("Remove Anthropic key", role: .destructive) {
                            isConfirmingRemoval = true
                        }
                        .disabled(model.isLoading)
                    }
                }

                if let error = model.errorMessage {
                    Section {
                        Text(error)
                            .foregroundStyle(AppTheme.stamp)
                            .accessibilityLabel("Error: \(error)")
                    }
                }
            }
            .navigationTitle("AI access")
            .navigationBarTitleDisplayMode(.inline)
            .disabled(model.isLoading)
            .overlay {
                if model.isLoading {
                    ProgressView()
                        .accessibilityLabel("Updating Anthropic key")
                }
            }
            .task { await model.load() }
            .onDisappear { model.apiKey = "" }
            .confirmationDialog(
                "Remove the Anthropic key?",
                isPresented: $isConfirmingRemoval,
                titleVisibility: .visible
            ) {
                Button("Remove key", role: .destructive) {
                    Task { await model.remove() }
                }
            } message: {
                Text("Trips you created cannot run new AI steps until you add a key again.")
            }
    }
}
