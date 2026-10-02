import Foundation
import Observation

@MainActor @Observable
final class AnthropicConsentViewModel {
    private(set) var status = AnthropicConsentStatus(
        anthropic: false,
        policyVersion: nil,
        grantedAt: nil
    )
    private(set) var isLoading = false
    private(set) var errorMessage: String?

    private let client: APIClient

    init(client: APIClient = .shared) {
        self.client = client
    }

    func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            status = try await client.anthropicConsent()
            errorMessage = nil
        } catch {
            errorMessage = AccountStore.message(for: error)
        }
    }

    @discardableResult
    func grant() async -> Bool {
        guard !isLoading else { return false }
        isLoading = true
        defer { isLoading = false }
        do {
            status = try await client.grantAnthropicConsent()
            errorMessage = nil
            return true
        } catch {
            errorMessage = AccountStore.message(for: error)
            return false
        }
    }

    func revoke() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            try await client.revokeAnthropicConsent()
            status = AnthropicConsentStatus(
                anthropic: false,
                policyVersion: nil,
                grantedAt: nil
            )
            errorMessage = nil
        } catch {
            errorMessage = AccountStore.message(for: error)
        }
    }
}
