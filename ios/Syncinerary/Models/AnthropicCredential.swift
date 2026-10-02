import Foundation

struct AnthropicCredentialStatus: Codable, Sendable, Equatable {
    let configured: Bool
    let lastFour: String?
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case configured
        case lastFour = "last_four"
        case updatedAt = "updated_at"
    }
}

struct AnthropicCredentialRequest: Codable, Sendable {
    let apiKey: String
    let consentToAnthropic: Bool

    enum CodingKeys: String, CodingKey {
        case apiKey = "api_key"
        case consentToAnthropic = "consent_to_anthropic"
    }
}
