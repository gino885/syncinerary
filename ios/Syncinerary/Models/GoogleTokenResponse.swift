import Foundation

struct GoogleTokenResponse: Decodable {
    let idToken: String
    enum CodingKeys: String, CodingKey { case idToken = "id_token" }
}
