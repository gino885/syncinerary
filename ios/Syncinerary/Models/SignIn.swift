import Foundation

struct SignInRequest: Codable, Sendable {
    let displayName: String
    let handle: String

    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case handle
    }
}

struct SignInResponse: Codable, Sendable {
    let token: String
    let account: Account
}
