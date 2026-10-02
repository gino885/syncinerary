import Foundation
import Observation

@MainActor @Observable
final class AnthropicCredentialViewModel {
    var apiKey = ""
    var hasConsent = false
    private(set) var status = AnthropicCredentialStatus(
        configured: false,
        lastFour: nil,
        updatedAt: nil
    )
    private(set) var isLoading = false
    private(set) var errorMessage: String?

    private let client: APIClient

    init(client: APIClient = .shared) {
        self.client = client
    }

    var canSave: Bool {
        !isLoading && hasConsent && !normalizedKey.isEmpty && validationMessage == nil
    }

    private var normalizedKey: String {
        apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var validationMessage: String? {
        guard !normalizedKey.isEmpty else { return nil }
        guard normalizedKey.hasPrefix("sk-ant-") else {
            return String(localized: "Use an Anthropic API key beginning with sk-ant-.")
        }
        guard !normalizedKey.contains(where: \.isWhitespace) else {
            return String(localized: "The key contains a space or line break. Paste the complete key again.")
        }
        guard (20...300).contains(normalizedKey.count) else {
            return String(localized: "This key looks incomplete. Paste the complete Anthropic API key.")
        }
        return nil
    }

    func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            status = try await client.anthropicCredential()
            errorMessage = nil
        } catch {
            errorMessage = AccountStore.message(for: error)
        }
    }

    @discardableResult
    func save() async -> Bool {
        guard canSave else { return false }
        isLoading = true
        defer { isLoading = false }
        do {
            status = try await client.saveAnthropicCredential(
                apiKey: normalizedKey,
                consentToAnthropic: hasConsent
            )
            apiKey = ""
            hasConsent = false
            errorMessage = nil
            return true
        } catch {
            errorMessage = AccountStore.message(for: error)
            return false
        }
    }

    func remove() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            try await client.removeAnthropicCredential()
            apiKey = ""
            hasConsent = false
            status = AnthropicCredentialStatus(
                configured: false,
                lastFour: nil,
                updatedAt: nil
            )
            errorMessage = nil
        } catch {
            errorMessage = AccountStore.message(for: error)
        }
    }
}
