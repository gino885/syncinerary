import Foundation

struct SocialSignInRequest: Codable, Sendable {
    let idToken: String
    let nonce: String
    var displayName: String? = nil
    var authorizationCode: String? = nil

    enum CodingKeys: String, CodingKey {
        case nonce
        case idToken = "id_token"
        case displayName = "display_name"
        case authorizationCode = "authorization_code"
    }
}
