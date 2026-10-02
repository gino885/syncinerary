import Foundation

struct SignInRequest: Codable, Sendable {
    let email: String
    let password: String
}

struct SignInResponse: Codable, Sendable {
    let token: String
    let account: Account
}
