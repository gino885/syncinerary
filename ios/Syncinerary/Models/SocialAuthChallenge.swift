import Foundation

struct SocialAuthChallenge: Decodable, Sendable {
    let nonce: String
    let clientID: String

    enum CodingKeys: String, CodingKey {
        case nonce
        case clientID = "client_id"
    }
}
