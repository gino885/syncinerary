import Foundation

struct EmailAuthRequest: Encodable, Sendable {
    let email: String
    var displayName: String? = nil
    var code: String? = nil
    var password: String? = nil

    enum CodingKeys: String, CodingKey {
        case email, code, password
        case displayName = "display_name"
    }
}
