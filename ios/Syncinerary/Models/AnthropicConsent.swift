import Foundation

struct AnthropicConsentStatus: Codable, Sendable, Equatable {
    let anthropic: Bool
    let policyVersion: String?
    let grantedAt: String?

    enum CodingKeys: String, CodingKey {
        case anthropic
        case policyVersion = "policy_version"
        case grantedAt = "granted_at"
    }
}

struct AnthropicConsentRequest: Codable, Sendable {
    let consentToAnthropic: Bool

    enum CodingKeys: String, CodingKey {
        case consentToAnthropic = "consent_to_anthropic"
    }
}

struct DeleteAccountRequest: Codable, Sendable {
    var currentPassword: String? = nil
    var socialIdentity: SocialSignInRequest? = nil
    let confirmation = "DELETE"

    enum CodingKeys: String, CodingKey {
        case currentPassword = "current_password"
        case socialIdentity = "social_identity"
        case confirmation
    }
}
